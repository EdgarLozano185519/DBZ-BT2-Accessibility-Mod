"""Binds the pure memory layer to a live PCSX2 PINE connection.

This is the only module that performs emulator I/O during navigation.  It keeps
reads bounded and cached so map discovery cannot monopolize the single PINE
service, and it degrades to progressively wider scans only when the cheap path
stops working.
"""

from __future__ import annotations

import math

import struct
import time
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
    other_actor_location,
    parse_local_interaction,
    parse_table,
    parse_transform,
    player_transform_is_valid,
    table_has_slot,
    table_is_live,
    vectors_match,
)
from .scan import TableScanner, choose_table, tables_in_window
from .surface import (
    LOCAL_EXIT,
    LOCAL_INTERACTION,
    Surface,
    tableless_world_surface,
    world_surface,
)


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


def _slotless_verdict(scanner: TableScanner, address: int, trust_slotless):
    """Accept, reject, or defer a table that has no player slot.

    Memory cannot tell whether such a table is current, so the minimap does:
    ``trust_slotless`` is True when the settled census shows at least one free
    destination, False when it shows none, None while it has not settled.  A
    table already accepted this visit stays accepted while the census is
    unsettled, which it is for a moment after every surface change, so a live
    map does not flicker off and on.  A rejection lasts the visit.
    """
    if address in scanner.rejected:
        return False
    if trust_slotless is True or address == scanner.last_address:
        return True
    if trust_slotless is False:
        scanner.reject(address)
        return False
    return None


def discover_world_map(
    pine, scanner: TableScanner, trust_slotless: bool | None = None
) -> Surface:
    """Find the live coordinate table without assuming where it lives.

    When there is none -- a map whose only destinations are story markers
    publishes no table at all -- the map is still a world map with a readable
    player, and is returned as one.  See ``tableless_world_surface``.
    """
    readings = dict(
        zip(
            PLAYER_SIMULATION_CANDIDATES + PLAYER_RENDER_CANDIDATES,
            pine.read_vector3_many(
                PLAYER_SIMULATION_CANDIDATES + PLAYER_RENDER_CANDIDATES
            ),
        )
    )
    mirror_set = discover_world_mirrors(readings)
    now = time.monotonic()
    if mirror_set.other is not None:
        scanner.note_other(mirror_set.other, now)
    # A second character is offered on every world map, table or not.  On a
    # table map it is the one destination whose position is exact: Android 20
    # (Android Saga, "Doctor Gero's Lab", 2026-09-10) flees from anything
    # nearer than about a thousand units and is caught only by landing on
    # him to the unit, which a minimap conversion never manages.
    remembered = scanner.other(now)
    companion = (
        other_actor_location(remembered) if remembered is not None else None
    )

    tiers = (
        scanner.targeted_windows(),
        scanner.band_windows(),
        scanner.sweep_windows(),
    )
    # Every structurally valid table seen during the sweep, kept in case none
    # of them can be confirmed live. See the fallback below.
    structural: dict[int, tuple] = {}
    # A slot-less table the minimap has not yet vouched for or against.
    undecided = False

    for windows in tiers:
        for window in windows:
            try:
                block = pine.read_aligned_range(window.base, window.size)
            except (ValueError, OSError):
                continue
            view = FlatMemory(window.base, block)
            candidates = []
            for candidate in tables_in_window(block, window):
                address = candidate[0]
                if not table_has_slot(view, address):
                    verdict = _slotless_verdict(scanner, address, trust_slotless)
                    if verdict is None:
                        undecided = True
                    if not verdict:
                        continue
                structural.setdefault(address, candidate)
                candidates.append(candidate)
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
                other=companion,
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
    if structural:
        chosen = choose_unconfirmed_table(structural.values(), mirror_set.position)
        if chosen is not None:
            address, locations = chosen
            return world_surface(
                table_address=address,
                player_address=mirror_set.authoritative,
                locations=locations,
                mirrors=mirror_set.all_addresses,
                liveness_confirmed=False,
                other=companion,
            )

    if undecided:
        raise MapNotReady(
            "A coordinate table with no player slot is waiting for the minimap "
            "to vouch for it"
        )

    # No table describes this map. That is a real state, not a failure: the
    # Namek map after the Zarbon fight draws one story marker and publishes no
    # coordinate records at all, while the player's position reads perfectly
    # well. What memory can still offer is any other character on the map.
    other = scanner.other(now)
    locations = (other_actor_location(other),) if other is not None else ()
    return tableless_world_surface(
        player_address=mirror_set.authoritative,
        locations=locations,
        mirrors=mirror_set.all_addresses,
    )


def _player_fit(locations, player) -> tuple[bool, float]:
    """Does this table describe ground the player is standing on?

    Returns whether the player is inside the destinations' bounding box, padded
    by the largest trigger radius, and how far the nearest destination is.
    """
    xs = [location.x for location in locations]
    zs = [location.z for location in locations]
    pad = max(location.radius for location in locations)
    inside = (
        min(xs) - pad <= player[0] <= max(xs) + pad
        and min(zs) - pad <= player[2] <= max(zs) + pad
    )
    nearest = min(
        math.hypot(location.x - player[0], location.z - player[2])
        for location in locations
    )
    return inside, nearest


# How much closer the winner must be than the runner-up to be believed.
UNCONFIRMED_TABLE_MARGIN = 0.5


def choose_unconfirmed_table(candidates, player):
    """Pick between tables when none could prove itself live, or refuse.

    Reaching here means the liveness check found nothing, which happens when
    the game stops updating a table's player slot -- observed on a second visit
    to Earth. With one table there is nothing to confuse it with. With several,
    the stale one is usually the previous map's, still resident, and describing
    ground the player is nowhere near.

    So geometry decides: the player should be standing within the destinations
    that describe them. If two tables both claim the player and neither is
    clearly closer, this refuses. Guessing which map you are on is exactly the
    failure the liveness check exists to prevent.
    """
    candidates = [entry for entry in candidates if entry[1]]
    if not candidates:
        return None
    if len(candidates) == 1:
        # Nothing to be confused with: the structural test is strict enough to
        # stand on its own, and refusing here left the player with no
        # destinations on a map that was working minutes earlier.
        return candidates[0]

    scored = []
    for address, locations in candidates:
        inside, nearest = _player_fit(locations, player)
        if inside:
            scored.append((nearest, address, locations))
    if not scored:
        return None
    scored.sort()
    if len(scored) > 1 and scored[0][0] > scored[1][0] * UNCONFIRMED_TABLE_MARGIN:
        return None  # Two plausible maps and no way to tell them apart.
    return scored[0][1], scored[0][2]


def discover_surface(
    pine, scanner: TableScanner, capture=None, trust_slotless: bool | None = None
) -> Surface:
    """Return the active surface, preferring the stronger local signature."""
    try:
        return discover_local_area(pine, verify_hud=capture is not None, capture=capture)
    except MapNotReady:
        pass
    return discover_world_map(pine, scanner, trust_slotless)


def refresh_surface(
    pine,
    scanner: TableScanner,
    surface: Surface,
    capture=None,
    trust_slotless: bool | None = None,
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
    return discover_surface(pine, scanner, capture, trust_slotless)


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
