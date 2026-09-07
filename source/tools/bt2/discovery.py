"""Binds the pure memory layer to a live PCSX2 PINE connection.

This is the only module that performs emulator I/O during navigation.  It keeps
reads bounded and cached so map discovery cannot monopolize the single PINE
service, and it degrades to progressively wider scans only when the cheap path
stops working.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from . import memory as mem
from .memory import (
    LOCAL_CAMERA_TRANSFORM_OFFSET,
    LOCAL_EXIT_RADIUS,
    LOCAL_INTERACTION_TRANSFORM_BLOCK,
    LOCAL_INTERACTION_TRANSFORM_BLOCK_SIZE,
    LOCAL_MODE,
    LOCAL_MODE_OFFSET,
    LOCAL_PLAYER_DESCRIPTOR_OFFSET,
    LOCAL_PLAYER_OFFSET,
    LOCAL_REPEATED_PLAYER_MATRIX_OFFSET,
    LOCAL_STAGE_SIGNATURE_ADDRESSES,
    LOCAL_TRANSFORM_BLOCK,
    LOCAL_TRANSFORM_BLOCK_SIZE,
    FlatMemory,
    Location,
    MapNotReady,
    PLAYER_OFFSET_FROM_TABLE,
    PLAYER_RENDER_CANDIDATES,
    PLAYER_SIMULATION_CANDIDATES,
    discover_world_mirrors,
    parse_local_interaction,
    parse_table,
    parse_transform,
    player_transform_is_valid,
    table_is_live,
    vectors_match,
)
from .scan import TableScanner, choose_table, tables_in_window
from .surface import LOCAL_EXIT, LOCAL_INTERACTION, Surface, world_surface


class LiveMemory:
    """A :class:`MemoryView` backed by PINE, with a per-tick region cache."""

    def __init__(self, pine):
        self.pine = pine
        self._regions: list[tuple[int, bytes]] = []

    def prime(self, address: int, size: int) -> bytes:
        aligned_base = address & ~7
        aligned_size = ((address + size + 7) & ~7) - aligned_base
        data = self.pine.read_aligned_range(aligned_base, aligned_size)
        self._regions.append((aligned_base, data))
        return data

    def invalidate(self) -> None:
        self._regions.clear()

    def read(self, address: int, size: int) -> bytes | None:
        for base, data in self._regions:
            offset = address - base
            if offset >= 0 and offset + size <= len(data):
                return data[offset : offset + size]
        return None


def _signature_key(words: tuple[int, ...]) -> str:
    return "".join(f"{word:08x}" for word in words)


def discover_local_area(pine, verify_hud: bool = True, capture=None) -> Surface:
    """Recognize a walkable Dragon Adventure area by structure alone.

    A local visit leaves the previous world table allocated, so the stronger
    duplicated-transform signature must be checked before the stale table can
    win.  Nothing here depends on a stage name or id, which is why an area the
    player has never reached identifies exactly like a familiar one.
    """
    block = pine.read_aligned_range(LOCAL_TRANSFORM_BLOCK, LOCAL_TRANSFORM_BLOCK_SIZE)
    view = FlatMemory(LOCAL_TRANSFORM_BLOCK, block)

    player_transform = parse_transform(view, LOCAL_TRANSFORM_BLOCK)
    camera_transform = parse_transform(
        view, LOCAL_TRANSFORM_BLOCK + LOCAL_CAMERA_TRANSFORM_OFFSET
    )
    repeated_player = parse_transform(
        view, LOCAL_TRANSFORM_BLOCK + LOCAL_REPEATED_PLAYER_MATRIX_OFFSET
    )
    if not player_transform or not camera_transform or not repeated_player:
        raise MapNotReady("No local Dragon Adventure transform block is active")

    player, repeated = pine.read_vector3_many(
        (
            LOCAL_TRANSFORM_BLOCK + LOCAL_PLAYER_OFFSET,
            LOCAL_TRANSFORM_BLOCK
            + LOCAL_REPEATED_PLAYER_MATRIX_OFFSET
            + LOCAL_PLAYER_OFFSET,
        )
    )
    if not vectors_match(player, repeated, 0.05):
        raise MapNotReady("The local player transform is not internally consistent")

    descriptor = struct.unpack_from("<I", block, LOCAL_PLAYER_DESCRIPTOR_OFFSET)[0]
    local_mode = struct.unpack_from("<I", block, LOCAL_MODE_OFFSET)[0]
    if not descriptor or local_mode != LOCAL_MODE:
        raise MapNotReady("The local player descriptor is not active")

    if verify_hud and capture is not None:
        from .vision import has_dragon_adventure_hud

        image = capture()
        if image is not None and not has_dragon_adventure_hud(image):
            raise MapNotReady(
                "The local transforms are not on a Dragon Adventure screen"
            )

    stage_signature = pine.read32_many(LOCAL_STAGE_SIGNATURE_ADDRESSES)

    interaction_block = pine.read_aligned_range(
        LOCAL_INTERACTION_TRANSFORM_BLOCK, LOCAL_INTERACTION_TRANSFORM_BLOCK_SIZE
    )
    interaction_view = FlatMemory(
        LOCAL_INTERACTION_TRANSFORM_BLOCK, interaction_block
    )
    location = parse_local_interaction(interaction_view)
    if location is None:
        location = Location(
            0,
            LOCAL_TRANSFORM_BLOCK + LOCAL_PLAYER_OFFSET,
            player[0],
            player[1],
            player[2],
            LOCAL_EXIT_RADIUS,
            "R1 world-map story route",
            True,
        )
        kind = LOCAL_EXIT
    else:
        kind = LOCAL_INTERACTION

    values = player_transform[0]
    return Surface(
        kind=kind,
        table_address=LOCAL_TRANSFORM_BLOCK,
        player_address=LOCAL_TRANSFORM_BLOCK + LOCAL_PLAYER_OFFSET,
        locations=(location,),
        fingerprint=_signature_key(stage_signature),
        stage_signature=stage_signature,
        descriptor=(descriptor, local_mode),
        local_right=(values[0], values[2]),
        local_forward=(values[8], values[10]),
    )


def discover_world_map(pine, scanner: TableScanner) -> Surface:
    """Find the live coordinate table without assuming where it lives."""
    readings = dict(
        zip(
            PLAYER_SIMULATION_CANDIDATES + PLAYER_RENDER_CANDIDATES,
            pine.read_vector3_many(
                PLAYER_SIMULATION_CANDIDATES + PLAYER_RENDER_CANDIDATES
            ),
        )
    )
    mirror_set = discover_world_mirrors(readings)

    tiers = (
        scanner.targeted_windows(),
        scanner.band_windows(),
        scanner.sweep_windows(),
    )
    # Every structurally valid table seen during the sweep, kept in case none
    # of them can be confirmed live. See the fallback below.
    structural: dict[int, tuple] = {}

    for windows in tiers:
        for window in windows:
            try:
                block = pine.read_aligned_range(window.base, window.size)
            except (ValueError, OSError):
                continue
            candidates = tables_in_window(block, window)
            for candidate in candidates:
                structural.setdefault(candidate[0], candidate)
            view = FlatMemory(window.base, block)
            # Liveness, not mere structural validity, decides.  A table whose
            # map is gone stays resident -- Earth's in particular, at the very
            # address the hint tier probes first -- so accepting the first
            # well-formed table silently navigated the wrong map.
            chosen = choose_table(
                candidates,
                scanner.last_address,
                lambda address, locations: table_is_live(
                    view,
                    address,
                    locations,
                    mirror_set.position,
                    tracker=scanner.liveness,
                ),
            )
            if chosen is None:
                if scanner.last_address is not None and any(
                    address == scanner.last_address for address, _ in candidates
                ):
                    # The cached table is still there but no longer describes
                    # where the player is; stop preferring it.
                    scanner.invalidate()
                continue
            address, locations = chosen
            scanner.accept(address, window.tier)
            return world_surface(
                table_address=address,
                player_address=mirror_set.authoritative,
                locations=locations,
                mirrors=mirror_set.all_addresses,
            )

    scanner.invalidate()

    # Nothing confirmed itself live. Liveness is decided by whether the table's
    # own player slot follows the player, and that slot can simply stop being
    # updated: observed on a second visit to Earth, where the slot sat frozen
    # 345 units from the player while the map, its minimap and its eight
    # destinations were all plainly the live ones. Refusing outright then left
    # the player with no destinations at all on a map that was working
    # perfectly well minutes earlier.
    #
    # So when exactly one well-formed table exists in the whole of RAM, use it.
    # The structural test is strict enough to have produced no false positives
    # across ~950 MiB, and "the only table there is" is a far weaker assumption
    # than "the first table found", which is the failure this guarded against.
    # Ambiguity still refuses: two tables and no liveness means genuinely not
    # knowing which map is current.
    if len(structural) == 1:
        address, locations = next(iter(structural.values()))
        return world_surface(
            table_address=address,
            player_address=mirror_set.authoritative,
            locations=locations,
            mirrors=mirror_set.all_addresses,
            liveness_confirmed=False,
        )

    raise MapNotReady(
        "No coordinate table matching the live player position was found"
    )


def discover_surface(pine, scanner: TableScanner, capture=None) -> Surface:
    """Return the active surface, preferring the stronger local signature."""
    try:
        return discover_local_area(pine, verify_hud=capture is not None, capture=capture)
    except MapNotReady:
        pass
    return discover_world_map(pine, scanner)


def refresh_surface(
    pine, scanner: TableScanner, surface: Surface, capture=None
) -> Surface:
    """Cheaply revalidate, while still noticing world/local transitions.

    Staying inside an already-confirmed local area skips the HUD cross-check:
    the duplicated transforms and local-mode descriptor are authoritative, and
    re-verifying every tick would make the guide depend on window focus.
    """
    if surface.is_local:
        try:
            return discover_local_area(pine, verify_hud=False)
        except MapNotReady:
            pass
    return discover_surface(pine, scanner, capture)


def validate_game(pine) -> None:
    info = pine.info()
    if info.serial != mem.SERIAL or info.crc.casefold() != mem.CRC:
        raise RuntimeError(
            f"Unsupported game build: {info.serial or 'unknown'} / "
            f"{info.crc or 'unknown'}; expected {mem.SERIAL} / {mem.CRC.upper()}"
        )


def scan_local_entities(pine, player):
    """Enumerate the characters and objects standing in a walking area.

    Expensive (a few hundred kilobytes), so callers should do this once on
    entering an area and then read the returned addresses live.
    """
    from .memory import (
        LOCAL_ENTITY_BLOCK,
        LOCAL_ENTITY_BLOCK_SIZE,
        find_local_entities,
    )

    half = LOCAL_ENTITY_BLOCK_SIZE // 2
    block = pine.read_aligned_range(LOCAL_ENTITY_BLOCK, half)
    block += pine.read_aligned_range(LOCAL_ENTITY_BLOCK + half, half)
    return find_local_entities(block, LOCAL_ENTITY_BLOCK, player)
