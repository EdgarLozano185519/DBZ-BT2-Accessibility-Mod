"""Offline checks for world-map discovery on the awkward maps.

None of these need PCSX2.  A fake PINE client serves a 32 MiB image with
tables planted where the scanner looks, and the player-position mirrors are
whatever the case needs.

Two situations first met on 2026-09-08 drive most of these:

- A map that publishes no coordinate table at all (Namek, after Vegeta beats
  Zarbon).  It must come back as a world map with no destinations, not as a
  failure, and the previous map's slot-less table must not be offered in its
  place just because it is still in RAM.
- Two characters on the map, so the simulation globals and the render block
  disagree by over a thousand units.  The render block is the player; the
  globals are a scratch that reports the other character.

Run:  python test_discovery.py
"""

from __future__ import annotations

import struct
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt2 import discovery, memory as mem  # noqa: E402
from bt2.scan import PRIMARY_BAND, TableScanner  # noqa: E402
from bt2.surface import NO_TABLE_FINGERPRINT  # noqa: E402

CHECKS = []


def check(function):
    CHECKS.append(function)
    return function


PLAYER = (-1075.98, -168.97, 418.33)
OTHER = (-243.61, -170.75, -699.60)
SIM = mem.PLAYER_SIMULATION_CANDIDATES
RENDER = mem.PLAYER_RENDER_CANDIDATES

# The six Blue islands points, as recorded in the map-6 profile.
BLUE_ISLANDS = (
    (-1560.406, 1857.055, 200.0),
    (505.19, 1069.195, 250.0),
    (1984.707, 1515.281, 250.0),
    (-1530.835, 151.807, 200.0),
    (-364.182, -219.492, 210.0),
    (-1492.072, -1025.279, 200.0),
)
# Inside the primary band, so the band tier finds it on every call and the
# rate-limited sweep never has to.
SLOTLESS_TABLE = PRIMARY_BAND + 0x50000
SLOTTED_TABLE = mem.LEGACY_LOCATION_TABLE


class FakePine:
    def __init__(self):
        self.image = bytearray(0x02000000)
        self.vectors: dict[int, tuple[float, float, float]] = {}

    def read_vector3_many(self, addresses):
        return tuple(self.vectors.get(a, (0.0, 0.0, 0.0)) for a in addresses)

    def read_vector3(self, address):
        return self.vectors.get(address, (0.0, 0.0, 0.0))

    def read_aligned_range(self, base, size, **_):
        return bytes(self.image[base : base + size])

    # -- builders --------------------------------------------------------
    def mirrors(self, simulation, render):
        for address in SIM:
            self.vectors[address] = simulation
        for address in RENDER:
            self.vectors[address] = render
        return self

    def plant_table(self, address, points, slot=None):
        for index, (x, z, radius) in enumerate(points):
            record = address + index * mem.LOCATION_STRIDE
            struct.pack_into("<fff", self.image, record, x, 0.0, z)
            struct.pack_into("<fff", self.image, record + 0x10, radius, radius, radius)
            struct.pack_into(
                "<fff", self.image, record + 0x20,
                mem.LOCATION_SENTINEL, mem.LOCATION_SENTINEL, mem.LOCATION_SENTINEL,
            )
            struct.pack_into("<I", self.image, record + 0x30, mem.LOCATION_RECORD_TYPE)
        if slot is not None:
            struct.pack_into(
                "<ffff", self.image, address + mem.PLAYER_OFFSET_FROM_TABLE,
                slot[0], slot[1], slot[2], 1.0,
            )
        return self


def readings(pine):
    return dict(zip(SIM + RENDER, pine.read_vector3_many(SIM + RENDER)))


# --- mirrors ----------------------------------------------------------------


@check
def test_agreeing_mirrors_keep_the_globals_authoritative():
    """Every map before Namek: both sets on the player, globals first."""
    pine = FakePine().mirrors(PLAYER, (PLAYER[0] + 30.0, PLAYER[1], PLAYER[2]))
    mirror_set = mem.discover_world_mirrors(readings(pine))
    assert mirror_set.authoritative == SIM[0]
    assert mirror_set.other is None
    assert len(mirror_set.all_addresses) == len(SIM) + len(RENDER)


@check
def test_disagreeing_mirrors_follow_the_render_block():
    """Two characters: the render block is the player, the globals are not."""
    pine = FakePine().mirrors(OTHER, PLAYER)
    mirror_set = mem.discover_world_mirrors(readings(pine))
    assert mirror_set.authoritative == RENDER[0]
    assert mirror_set.position == PLAYER
    assert mirror_set.other == OTHER
    # Teleport writes all_addresses; the scratch must not be among them.
    assert mirror_set.simulation == ()
    assert set(mirror_set.all_addresses) == set(RENDER)


@check
def test_render_block_alone_is_enough():
    """Globals unreadable, render fine: still a position."""
    pine = FakePine().mirrors((float("nan"),) * 3, PLAYER)
    mirror_set = mem.discover_world_mirrors(readings(pine))
    assert mirror_set.authoritative == RENDER[0]
    assert mirror_set.other is None


@check
def test_no_render_quorum_still_refuses():
    pine = FakePine().mirrors(PLAYER, (float("nan"),) * 3)
    try:
        mem.discover_world_mirrors(readings(pine))
    except mem.MapNotReady:
        return
    raise AssertionError("a missing render quorum was accepted")


# --- slot-less tables and the minimap ---------------------------------------


def namek(pine=None):
    """The Namek situation: stale slot-less table, two characters."""
    pine = pine or FakePine()
    pine.mirrors(OTHER, PLAYER).plant_table(SLOTLESS_TABLE, BLUE_ISLANDS)
    return pine


@check
def test_a_slotless_table_waits_for_the_minimap():
    """Census unsettled, nothing accepted yet: neither trusted nor rejected."""
    try:
        discovery.discover_world_map(namek(), TableScanner(), trust_slotless=None)
    except mem.MapNotReady as error:
        assert "vouch" in str(error), error
        return
    raise AssertionError("an unvouched slot-less table was decided on")


@check
def test_a_slotless_table_is_accepted_when_free_markers_show():
    scanner = TableScanner()
    surface = discovery.discover_world_map(namek(), scanner, trust_slotless=True)
    assert surface.has_table
    assert surface.table_address == SLOTLESS_TABLE
    assert len(surface.locations) == 6
    # And stays accepted while the census re-settles after the identity change.
    again = discovery.discover_world_map(namek(), scanner, trust_slotless=None)
    assert again.identity == surface.identity


@check
def test_a_slotless_table_is_rejected_when_no_free_markers_show():
    """The actual Namek failure: one red marker, six stale points offered."""
    scanner = TableScanner()
    surface = discovery.discover_world_map(namek(), scanner, trust_slotless=False)
    assert not surface.has_table
    assert surface.fingerprint == NO_TABLE_FINGERPRINT
    assert surface.player_address == RENDER[0]
    assert SLOTLESS_TABLE in scanner.rejected
    # The other character is what memory can still offer.
    assert len(surface.locations) == 1
    other = surface.locations[0]
    assert other.label == mem.OTHER_ACTOR_NAME
    assert (other.x, other.z) == (OTHER[0], OTHER[2])
    assert "no destination table" in surface.describe()
    assert "1 other character" in surface.describe()


@check
def test_a_rejection_holds_while_the_census_resettles():
    """After the table-less surface is announced the inventory resets; the
    stale table must not come back as undecided and flip the surface."""
    scanner = TableScanner()
    discovery.discover_world_map(namek(), scanner, trust_slotless=False)
    surface = discovery.discover_world_map(namek(), scanner, trust_slotless=None)
    assert not surface.has_table
    assert surface.identity == ("world", NO_TABLE_FINGERPRINT)


@check
def test_the_other_character_survives_a_scratch_flicker():
    """One read in fifty shows the player in the globals; the character
    stays on offer through it rather than vanishing for a tick."""
    scanner = TableScanner()
    discovery.discover_world_map(namek(), scanner, trust_slotless=False)
    flicker = FakePine().mirrors(PLAYER, PLAYER).plant_table(SLOTLESS_TABLE, BLUE_ISLANDS)
    surface = discovery.discover_world_map(flicker, scanner, trust_slotless=False)
    assert len(surface.locations) == 1
    assert surface.player_address == SIM[0]  # agreeing sets: the old rule holds


@check
def test_reset_visit_forgets_the_rejection():
    scanner = TableScanner()
    discovery.discover_world_map(namek(), scanner, trust_slotless=False)
    scanner.reset_visit()
    assert not scanner.rejected
    try:
        discovery.discover_world_map(namek(), scanner, trust_slotless=None)
    except mem.MapNotReady:
        return
    raise AssertionError("the rejection outlived reset_visit")


@check
def test_no_table_anywhere_is_a_world_map_not_a_failure():
    pine = FakePine().mirrors(PLAYER, PLAYER)
    surface = discovery.discover_world_map(pine, TableScanner(), trust_slotless=None)
    assert not surface.has_table
    assert surface.locations == ()
    assert surface.player_address == SIM[0]
    assert surface.describe() == "New map world map with no destination table"


@check
def test_a_slotted_live_table_ignores_the_minimap_rule():
    """Earth's table proves itself by its slot; the census has no say."""
    pine = FakePine().mirrors(PLAYER, PLAYER)
    pine.plant_table(
        SLOTTED_TABLE,
        BLUE_ISLANDS + ((300.0, -1872.0, 280.0), (1450.0, -1221.0, 280.0)),
        slot=PLAYER,
    )
    surface = discovery.discover_world_map(pine, TableScanner(), trust_slotless=False)
    assert surface.has_table
    assert surface.table_address == SLOTTED_TABLE
    assert len(surface.locations) == 8
    assert surface.other is None


EARTH_POINTS = BLUE_ISLANDS + ((300.0, -1872.0, 280.0), (1450.0, -1221.0, 280.0))


@check
def test_a_table_map_still_offers_the_other_character():
    """Android 20 on Blue islands, 2026-09-10: a table map with a second actor.

    The globals held him 1024 units from the player while the render block
    held the player, exactly as on Namek -- but this map has a table, and the
    character used to be offered only where there was none.
    """
    pine = FakePine().mirrors(OTHER, PLAYER).plant_table(
        SLOTTED_TABLE, EARTH_POINTS, slot=PLAYER
    )
    surface = discovery.discover_world_map(pine, TableScanner(), trust_slotless=False)
    assert surface.has_table
    assert len(surface.locations) == 8
    assert surface.other is not None
    assert surface.other.label == mem.OTHER_ACTOR_NAME
    assert (surface.other.x, surface.other.z) == (OTHER[0], OTHER[2])
    # The character is not a table entry, so the map's identity is the same
    # with him and without him.
    alone = FakePine().mirrors(PLAYER, PLAYER).plant_table(
        SLOTTED_TABLE, EARTH_POINTS, slot=PLAYER
    )
    unaccompanied = discovery.discover_world_map(
        alone, TableScanner(), trust_slotless=False
    )
    assert unaccompanied.other is None
    assert unaccompanied.identity == surface.identity


@check
def test_landing_on_the_other_character_is_exact():
    """Android 20 fled from 60 units and was caught at 0; no depth, no margin."""
    from bt2.teleport import _world_landing

    target = mem.other_actor_location(OTHER)
    assert _world_landing(PLAYER, target) == (OTHER[0], OTHER[1], OTHER[2])
    # An ordinary destination still keeps the player's own altitude.
    point = mem.Location(0, 0, 100.0, 0.0, 200.0, 400.0)
    assert _world_landing(PLAYER, point) == (100.0, PLAYER[1], 200.0)


def main() -> int:
    failures = []
    for function in CHECKS:
        try:
            function()
        except Exception:
            failures.append(function.__name__)
            print(f"FAIL {function.__name__}:")
            traceback.print_exc()
    print(f"{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
