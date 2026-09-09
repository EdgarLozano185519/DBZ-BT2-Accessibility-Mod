"""The active navigation surface: a world map or a walkable local area."""

from __future__ import annotations

from dataclasses import dataclass, field

from .memory import Location, fingerprint_locations

WORLD = "world"
VISION_WORLD = "vision_world"
LOCAL_INTERACTION = "local_interaction"
LOCAL_EXIT = "local_exit"

# The identity of every world map that publishes no coordinate table.  One
# profile serves them all, which means a scale learned on one is offered on
# the next; the scale has agreed to within six percent across every map
# measured, and C re-learns it in six hops if it does not.
NO_TABLE_FINGERPRINT = "no-table"


@dataclass(frozen=True)
class Surface:
    kind: str
    table_address: int
    player_address: int
    locations: tuple[Location, ...]
    fingerprint: str
    name: str | None = None
    named: bool = False
    stage_signature: tuple[int, ...] = ()
    mirrors: tuple[int, ...] = ()
    local_right: tuple[float, float] | None = None
    local_forward: tuple[float, float] | None = None
    # False when the table could not prove itself live and was accepted only
    # because it was the sole one in memory. Everything still works; the guide
    # says so once rather than pretending to a certainty it does not have.
    liveness_confirmed: bool = True
    descriptor: tuple[int, ...] = ()
    label_key: str | None = None

    @property
    def is_local(self) -> bool:
        return self.kind.startswith("local")

    @property
    def is_vision_only(self) -> bool:
        return self.kind == VISION_WORLD

    @property
    def requires_world_return(self) -> bool:
        return self.kind == LOCAL_EXIT

    @property
    def has_table(self) -> bool:
        return self.kind == WORLD and self.table_address != 0

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.is_local:
            return "New area"
        return "New map"

    @property
    def identity(self) -> tuple:
        """Stable across player movement, changes when the surface changes."""
        if self.is_local:
            return (self.kind, self.fingerprint, self.descriptor)
        # Spoken labels are presentation only, including during teleport's
        # independent memory revalidation. They must never change map identity.
        return (WORLD, self.fingerprint)

    def describe(self) -> str:
        if self.is_local:
            return f"{self.display_name} local area"
        if self.is_vision_only:
            return f"{self.display_name} world map"
        if not self.has_table:
            extra = ""
            if self.locations:
                extra = f", {len(self.locations)} other character"
                extra += "s" if len(self.locations) != 1 else ""
            return f"{self.display_name} world map with no destination table{extra}"
        return (
            f"{self.display_name} world map with {len(self.locations)} "
            f"{'point' if len(self.locations) == 1 else 'points'}"
        )


def world_surface(
    table_address: int,
    player_address: int,
    locations: tuple[Location, ...],
    mirrors: tuple[int, ...] = (),
    liveness_confirmed: bool = True,
) -> Surface:
    return Surface(
        kind=WORLD,
        table_address=table_address,
        player_address=player_address,
        locations=locations,
        fingerprint=fingerprint_locations(locations),
        mirrors=mirrors,
        liveness_confirmed=liveness_confirmed,
    )


def tableless_world_surface(
    player_address: int,
    locations: tuple[Location, ...] = (),
    mirrors: tuple[int, ...] = (),
) -> Surface:
    """A world map whose position is readable but which publishes no table.

    First met on the Namek map after Vegeta defeats Zarbon: one red marker, no
    yellow ones, and nothing in RAM shaped like a coordinate record.  Guidance,
    G and calibration all work from the player's position and the minimap; the
    only destinations are the ones memory can still offer -- another character
    standing on the map -- and, once calibrated, the story marker.
    """
    return Surface(
        kind=WORLD,
        table_address=0,
        player_address=player_address,
        locations=locations,
        fingerprint=NO_TABLE_FINGERPRINT,
        mirrors=mirrors,
    )


def vision_world_surface() -> Surface:
    """A usable minimap with no currently discoverable coordinate table.

    It supports the primary screen-space guide immediately.  Player memory and
    teleport simply remain unavailable until normal discovery catches up.
    """
    return Surface(
        kind=VISION_WORLD,
        table_address=0,
        player_address=0,
        locations=(),
        fingerprint="live-minimap",
        name="Dragon Adventure",
        named=True,
    )
