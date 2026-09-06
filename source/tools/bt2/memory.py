"""Pure parsing of DBZ BT2's emulated PS2 RAM.

Nothing in this module talks to PCSX2.  Everything operates on a
:class:`MemoryView`, which may be a live PINE adapter, a full RAM dump, or a
handful of sparse regions recorded in the test corpus.  That separation is what
lets map discovery be exercised offline against recorded captures.

No function here assumes a particular map.  Structures are recognized by their
shape -- sentinel words, record types, orthonormal transform bases -- so a map
that has never been visited parses exactly like a known one.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from typing import Iterable, Protocol

SERIAL = "SLUS-21441"
CRC = "fe961d28"

# --- Coordinate-table record layout -----------------------------------------
# Each record is 0x40 bytes: position, radius triple, a 99999.0 sentinel triple,
# then a record-type word.  The sentinel is what makes the table findable
# without knowing its address.
LOCATION_STRIDE = 0x40
LOCATION_SENTINEL = 99_999.0
# Word 12 is a record type, not a constant.  Every Earth record is a 2, which
# made it look fixed; a second map carries two further sentinel records with a
# type of 0 and much larger radii (500 and 400 against 200-250), one of them
# sitting within 2.4 units of a type-2 destination.  Only type 2 is a place the
# player travels to, so the parser keeps requiring it -- but it is a filter on a
# real field, not a structural constant.
LOCATION_RECORD_TYPE = 2
PLAYER_OFFSET_FROM_TABLE = 0x500
MAX_LOCATION_COUNT = PLAYER_OFFSET_FROM_TABLE // LOCATION_STRIDE
MIN_LOCATION_COUNT = 2

# The Earth table observed in every research capture.  Retained only as a scan
# hint so the common case costs one small read; discovery never requires it.
LEGACY_LOCATION_TABLE = 0x00E23000

PLAYER_MATCH_TOLERANCE = 2.0
# The render mirror is not the simulation mirror plus lag -- it is a different
# point that sits a roughly constant distance away.  Measured live, the gap is
# the same whether the player is stationary or flying hard (38.4 units still,
# 33.4 at speed), and a recorded world capture reaches 57.1.  A 30-unit gate
# therefore sat inside the normal band and rejected a healthy transform about a
# fifth of the time, which read as navigation closing whenever the player moved.
# What this gate is actually for is a half-loaded frame, where the two mirrors
# describe different maps and are hundreds of units apart.
MAX_RENDER_LAG_DISTANCE = 200.0

# --- Local (walkable) area structures ---------------------------------------
LOCAL_TRANSFORM_BLOCK = 0x00E600E0
LOCAL_TRANSFORM_BLOCK_SIZE = 0x108
LOCAL_PLAYER_OFFSET = 0x30
LOCAL_CAMERA_TRANSFORM_OFFSET = 0x40
LOCAL_REPEATED_PLAYER_MATRIX_OFFSET = 0x80
LOCAL_PLAYER_DESCRIPTOR_OFFSET = 0xF0
LOCAL_MODE_OFFSET = 0xF4
LOCAL_MODE = 2

LOCAL_INTERACTION_TRANSFORM_BLOCK = 0x00E234D0
LOCAL_INTERACTION_TRANSFORM_BLOCK_SIZE = 0x240
LOCAL_INTERACTION_TRANSFORM_OFFSET = 0x40
LOCAL_INTERACTION_POSITION_OFFSET = LOCAL_INTERACTION_TRANSFORM_OFFSET + 0x30
LOCAL_ACTOR_MIRROR_TRANSFORM_OFFSETS = (0xE0, 0x120, 0x1C0, 0x200)
LOCAL_INTERACTION_RADIUS = 2.0
LOCAL_EXIT_RADIUS = 1.0

LOCAL_PLAYER_MIRROR_BLOCK = 0x00E60000
LOCAL_PLAYER_MIRROR_BLOCK_SIZE = 0x1B0
LOCAL_PLAYER_MIRROR_ALIGNMENT = 0x10
LOCAL_REQUIRED_PLAYER_MIRRORS = (
    LOCAL_TRANSFORM_BLOCK + LOCAL_PLAYER_OFFSET,
    LOCAL_TRANSFORM_BLOCK + LOCAL_REPEATED_PLAYER_MATRIX_OFFSET + LOCAL_PLAYER_OFFSET,
)
MIN_LOCAL_PLAYER_MIRRORS = 3
MAX_LOCAL_PLAYER_MIRRORS = 16
LOCAL_TELEPORT_STANDOFF = 1.0

LOCAL_STAGE_SIGNATURE_ADDRESSES = (
    0x013EF200,
    0x013EF204,
    0x013EF208,
    0x013EF20C,
    0x01409400,
    0x01409404,
    0x01409408,
    0x0140940C,
)

# --- Overworld player transform mirrors -------------------------------------
# These are candidates, not requirements.  A quorum of agreeing simulation and
# render mirrors is enough; demanding all of them made a single unpopulated
# address on an unvisited map disable navigation entirely.
PLAYER_SIMULATION_CANDIDATES = (
    0x0038B130,
    0x0038B170,
    0x0038B1B0,
)
PLAYER_RENDER_CANDIDATES = (
    0x00E5C120,
    0x00E5C140,
    0x00E5C150,
    0x00E5C1B0,
    0x00E5C230,
    0x00E5C240,
)
MIN_SIMULATION_QUORUM = 2
MIN_RENDER_QUORUM = 3


class MapNotReady(RuntimeError):
    """Connected, but no stable Dragon Adventure surface is available."""


class ObjectiveNotReady(MapNotReady):
    """The surface exists, but its live story marker cannot be read yet."""


# --- Memory access ----------------------------------------------------------


class MemoryView(Protocol):
    """Random access to emulated PS2 RAM."""

    def read(self, address: int, size: int) -> bytes | None:
        """Return ``size`` bytes at ``address``, or ``None`` if unavailable."""


@dataclass
class FlatMemory:
    """A contiguous block, such as a full RAM dump or one bounded read."""

    base: int
    data: bytes

    def read(self, address: int, size: int) -> bytes | None:
        offset = address - self.base
        if offset < 0 or size < 0 or offset + size > len(self.data):
            return None
        return self.data[offset : offset + size]


@dataclass
class SparseMemory:
    """Several disjoint regions, used by the offline corpus fixtures."""

    regions: list[tuple[int, bytes]] = field(default_factory=list)

    def add(self, base: int, data: bytes) -> "SparseMemory":
        self.regions.append((base, data))
        self.regions.sort(key=lambda region: region[0])
        return self

    def read(self, address: int, size: int) -> bytes | None:
        for base, data in self.regions:
            offset = address - base
            if offset >= 0 and offset + size <= len(data):
                return data[offset : offset + size]
        return None


def read_floats(memory: MemoryView, address: int, count: int) -> tuple[float, ...] | None:
    raw = memory.read(address, count * 4)
    if raw is None:
        return None
    return struct.unpack(f"<{count}f", raw)


def read_u32(memory: MemoryView, address: int) -> int | None:
    raw = memory.read(address, 4)
    if raw is None:
        return None
    return struct.unpack("<I", raw)[0]


# --- Coordinate tables ------------------------------------------------------


@dataclass(frozen=True)
class Location:
    index: int
    address: int
    x: float
    y: float
    z: float
    radius: float
    name: str | None = None
    use_y: bool = False

    @property
    def label(self) -> str:
        return self.name or f"map point {self.index + 1}"

    def renamed(self, name: str | None) -> "Location":
        return Location(
            self.index,
            self.address,
            self.x,
            self.y,
            self.z,
            self.radius,
            name,
            self.use_y,
        )


def parse_location(memory: MemoryView, address: int, index: int) -> Location | None:
    """Validate one coordinate record purely by its shape."""
    values = read_floats(memory, address, 3)
    radii = read_floats(memory, address + 0x10, 3)
    sentinels = read_floats(memory, address + 0x20, 3)
    record_type = read_u32(memory, address + 0x30)
    if values is None or radii is None or sentinels is None or record_type is None:
        return None
    x, y, z = values
    radius, radius_y, radius_z = radii
    if not (
        all(math.isfinite(value) for value in (x, y, z, radius, radius_y, radius_z))
        and max(abs(x), abs(y), abs(z)) < 1_000_000.0
        and 1.0 <= radius <= 5_000.0
        and abs(radius - radius_y) < 0.02
        and abs(radius - radius_z) < 0.02
        and all(abs(value - LOCATION_SENTINEL) < 0.2 for value in sentinels)
        and record_type == LOCATION_RECORD_TYPE
    ):
        return None
    return Location(index, address, x, y, z, radius)


def parse_table(memory: MemoryView, address: int) -> tuple[Location, ...]:
    locations = []
    for index in range(MAX_LOCATION_COUNT):
        location = parse_location(memory, address + index * LOCATION_STRIDE, index)
        if location is None:
            break
        locations.append(location)
    return tuple(locations)


def player_transform_is_valid(memory: MemoryView, address: int) -> bool:
    values = read_floats(memory, address, 4)
    if values is None:
        return False
    x, y, z, homogeneous = values
    return (
        all(math.isfinite(value) for value in (x, y, z, homogeneous))
        and max(abs(x), abs(y), abs(z)) < 1_000_000.0
        and abs(homogeneous - 1.0) < 0.01
    )


def find_tables(block: bytes, base: int) -> list[tuple[int, tuple[Location, ...]]]:
    """Locate every coordinate table inside one contiguous block.

    Across the 29 research dumps (~950 MiB) this sentinel-plus-record test
    produced no false positives, which is what makes a widened scan safe.
    """
    marker = struct.pack(
        "<fff", LOCATION_SENTINEL, LOCATION_SENTINEL, LOCATION_SENTINEL
    )
    memory = FlatMemory(base, block)
    record_addresses: set[int] = set()
    offset = 0
    while True:
        offset = block.find(marker, offset)
        if offset < 0:
            break
        address = base + offset - 0x20
        if address % 4 == 0 and parse_location(memory, address, 0) is not None:
            record_addresses.add(address)
        offset += 4

    starts = sorted(
        address
        for address in record_addresses
        if address - LOCATION_STRIDE not in record_addresses
    )
    tables = []
    for table_address in starts:
        locations = parse_table(memory, table_address)
        if len(locations) >= MIN_LOCATION_COUNT:
            tables.append((table_address, locations))
    return tables


# --- Transforms -------------------------------------------------------------


def parse_transform(
    memory: MemoryView, address: int
) -> tuple[tuple[float, ...], tuple[float, float, float]] | None:
    """Validate a conventional 4x4 transform with an orthonormal basis."""
    values = read_floats(memory, address, 16)
    if values is None or not all(math.isfinite(value) for value in values):
        return None
    if not (
        max(abs(values[index]) for index in (3, 7, 11)) <= 0.02
        and abs(values[15] - 1.0) <= 0.02
        and max(abs(values[index]) for index in (12, 13, 14)) < 1_000_000.0
    ):
        return None
    axes = (values[0:3], values[4:7], values[8:11])
    lengths = [
        math.sqrt(sum(component * component for component in axis)) for axis in axes
    ]
    if not all(0.8 <= length <= 1.2 for length in lengths):
        return None
    dots = (
        sum(first * second for first, second in zip(axes[0], axes[1])),
        sum(first * second for first, second in zip(axes[0], axes[2])),
        sum(first * second for first, second in zip(axes[1], axes[2])),
    )
    if max(abs(dot) for dot in dots) > 0.2:
        return None
    return values, (values[12], values[13], values[14])


def vectors_match(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    tolerance: float = PLAYER_MATCH_TOLERANCE,
) -> bool:
    return all(
        abs(first[index] - second[index]) <= tolerance for index in range(3)
    )


# --- Quorum mirror discovery ------------------------------------------------


@dataclass(frozen=True)
class MirrorSet:
    """The live player-position mirrors that agree with each other."""

    simulation: tuple[int, ...]
    render: tuple[int, ...]
    position: tuple[float, float, float]

    @property
    def all_addresses(self) -> tuple[int, ...]:
        return self.simulation + self.render

    @property
    def authoritative(self) -> int:
        return self.simulation[0]


def _planar_matches(
    first: tuple[float, float, float],
    second: tuple[float, float, float],
    tolerance: float = PLAYER_MATCH_TOLERANCE,
) -> bool:
    return (
        abs(first[0] - second[0]) <= tolerance
        and abs(first[2] - second[2]) <= tolerance
    )


def _largest_agreeing_group(
    readings: dict[int, tuple[float, float, float]]
) -> tuple[tuple[int, ...], tuple[float, float, float]] | None:
    """Pick the biggest cluster of mutually agreeing positions."""
    best: tuple[int, ...] = ()
    best_position: tuple[float, float, float] | None = None
    for anchor_address, anchor in readings.items():
        group = tuple(
            address
            for address, value in readings.items()
            if _planar_matches(anchor, value)
        )
        if len(group) > len(best):
            best = group
            best_position = anchor
    if best_position is None or not best:
        return None
    return best, best_position


def discover_world_mirrors(
    readings: dict[int, tuple[float, float, float]],
) -> MirrorSet:
    """Find agreeing simulation and render mirrors without demanding all of them.

    ``readings`` must come from a single emulated frame.  Addresses whose values
    are absent or implausible are simply not counted toward the quorum, so an
    unvisited map that leaves one render slot unpopulated still navigates.
    """

    def plausible(vector: tuple[float, float, float]) -> bool:
        return all(math.isfinite(value) for value in vector) and max(
            abs(value) for value in vector
        ) < 1_000_000.0

    simulation_readings = {
        address: readings[address]
        for address in PLAYER_SIMULATION_CANDIDATES
        if address in readings and plausible(readings[address])
    }
    render_readings = {
        address: readings[address]
        for address in PLAYER_RENDER_CANDIDATES
        if address in readings and plausible(readings[address])
    }

    simulation_group = _largest_agreeing_group(simulation_readings)
    if simulation_group is None or len(simulation_group[0]) < MIN_SIMULATION_QUORUM:
        raise MapNotReady(
            "The overworld simulation transform is not stable yet "
            f"({0 if simulation_group is None else len(simulation_group[0])} of "
            f"{MIN_SIMULATION_QUORUM} required mirrors agree)"
        )
    simulation_addresses, simulation_position = simulation_group

    render_group = _largest_agreeing_group(render_readings)
    if render_group is None or len(render_group[0]) < MIN_RENDER_QUORUM:
        raise MapNotReady(
            "The overworld render transforms are not stable yet "
            f"({0 if render_group is None else len(render_group[0])} of "
            f"{MIN_RENDER_QUORUM} required mirrors agree)"
        )
    render_addresses, render_position = render_group

    render_lag = math.hypot(
        render_position[0] - simulation_position[0],
        render_position[2] - simulation_position[2],
    )
    if render_lag > MAX_RENDER_LAG_DISTANCE:
        raise MapNotReady(
            f"The overworld render transform is still loading "
            f"({render_lag:.1f} units apart)"
        )

    ordered_simulation = tuple(
        address for address in PLAYER_SIMULATION_CANDIDATES
        if address in simulation_addresses
    )
    ordered_render = tuple(
        address for address in PLAYER_RENDER_CANDIDATES if address in render_addresses
    )
    return MirrorSet(ordered_simulation, ordered_render, simulation_position)


def find_local_player_mirrors(block: bytes, base: int) -> tuple[int, ...]:
    """Find every exact copy of the local player position in a small block."""
    player_offset = LOCAL_TRANSFORM_BLOCK + LOCAL_PLAYER_OFFSET - base
    if player_offset < 0 or player_offset + 12 > len(block):
        return ()
    player = struct.unpack_from("<3f", block, player_offset)
    if not all(math.isfinite(value) for value in player):
        return ()
    mirrors = []
    for offset in range(0, len(block) - 11, LOCAL_PLAYER_MIRROR_ALIGNMENT):
        candidate = struct.unpack_from("<3f", block, offset)
        if vectors_match(player, candidate, 0.0001):
            mirrors.append(base + offset)
    result = tuple(mirrors)
    if not all(address in result for address in LOCAL_REQUIRED_PLAYER_MIRRORS):
        return ()
    if not MIN_LOCAL_PLAYER_MIRRORS <= len(result) <= MAX_LOCAL_PLAYER_MIRRORS:
        return ()
    return result


def parse_local_interaction(memory: MemoryView) -> Location | None:
    """Return the authored local interaction after validating its actor pool."""
    base = LOCAL_INTERACTION_TRANSFORM_BLOCK
    primary = parse_transform(memory, base)
    interaction = parse_transform(memory, base + LOCAL_INTERACTION_TRANSFORM_OFFSET)
    mirrors = tuple(
        parse_transform(memory, base + offset)
        for offset in LOCAL_ACTOR_MIRROR_TRANSFORM_OFFSETS
    )
    if primary is None or interaction is None or any(
        mirror is None for mirror in mirrors
    ):
        return None
    primary_position = primary[1]
    if not all(
        vectors_match(primary_position, mirror[1], 0.05)
        for mirror in mirrors
        if mirror is not None
    ):
        return None
    x, y, z = interaction[1]
    if max(abs(x), abs(y), abs(z)) >= 100_000.0:
        return None
    return Location(
        0,
        base + LOCAL_INTERACTION_POSITION_OFFSET,
        x,
        y,
        z,
        LOCAL_INTERACTION_RADIUS,
        "local story interaction",
        True,
    )


def distance_to(player: tuple[float, float, float], location: Location) -> float:
    if location.use_y:
        return math.sqrt(
            (location.x - player[0]) ** 2
            + (location.y - player[1]) ** 2
            + (location.z - player[2]) ** 2
        )
    return math.hypot(location.x - player[0], location.z - player[2])


# --- Trigger volumes --------------------------------------------------------
# A destination record carries an isotropic radius triple -- 280/280/280,
# 250/250/250 and so on -- so the volume the game tests against is a sphere,
# not a circle.  Every point sits at y = 0 while the overworld is flown well
# below it (-170 in the recorded captures, -121 and -154 in later live
# sessions), so a fixed vertical offset eats into every sphere:
#
#     radius 200 at 170 below  ->  only 105 units of horizontal reach
#     radius 210 at 170 below  ->        123
#     radius 300 at 170 below  ->        247
#
# Matching on X and Z alone therefore reports arrival while the player is still
# outside the volume, which is exactly "standing on the point and Cross does
# nothing".  Worse, a point whose radius is smaller than the current altitude
# offset cannot be entered at all without descending, and no amount of
# horizontal flying will fix it.


def trigger_distance(
    player: tuple[float, float, float], location: Location
) -> float:
    """True distance to a destination's centre, altitude included."""
    return math.sqrt(
        (location.x - player[0]) ** 2
        + (location.y - player[1]) ** 2
        + (location.z - player[2]) ** 2
    )


def within_trigger(
    player: tuple[float, float, float], location: Location
) -> bool:
    """Whether the player is inside the sphere the game actually tests."""
    return trigger_distance(player, location) <= location.radius


def horizontal_reach(
    location: Location, player_y: float
) -> float | None:
    """How close horizontally the player must get, at their current altitude.

    ``None`` when the sphere cannot be entered from this altitude at all.
    """
    vertical = abs(location.y - player_y)
    remaining = location.radius**2 - vertical**2
    if remaining <= 0.0:
        return None
    return math.sqrt(remaining)


def fingerprint_locations(locations: Iterable[Location]) -> str:
    """A stable identity for a map, derived only from its own geometry.

    Independent of load address, chapter, and which points are unlocked -- the
    table is allocated whole, so a locked destination still contributes its
    coordinates.
    """
    import hashlib

    digest = hashlib.sha256()
    for location in locations:
        digest.update(
            struct.pack(
                "<iii",
                int(round(location.x)),
                int(round(location.z)),
                int(round(location.radius)),
            )
        )
    return digest.hexdigest()[:16]


# --- Table liveness ---------------------------------------------------------
# A coordinate table staying resident after its map is gone is the whole reason
# navigation could silently run on the wrong map: the scanner's hint tier probes
# Earth's historical address first, so a stale Earth table won anywhere.
#
# The table publishes its own player slot at +0x500, and across all 24 world
# captures that slot matches the live simulation transform to under two units
# and follows movement.  On every local-area capture it holds a stale value
# instead.  Agreement is therefore a direct test of whether a table belongs to
# the surface being played.

# Distance decides liveness only when the slot is plainly on top of the player.
# On the recorded captures it always is -- every world capture agrees to 0.0
# units -- but a later live session measured the slot holding a steady 12 to 34
# unit offset while faithfully following the player, and the stale slot left
# behind in a walking area sits 24.8 units away.  Those ranges overlap, so no
# threshold separates live from stale, and the 20-unit one closed navigation on
# a healthy table roughly half the time.
#
# Motion does separate them: a live slot moves when the player moves, and a
# stale one is frozen.  That is what LivenessTracker tests.  This tolerance
# survives as the fast path and as the answer when there is no motion history.
TABLE_LIVENESS_TOLERANCE = 20.0
# Deliberately NOT part of the liveness test.  Bounding the player to the map's
# own point extent looked reasonable and was wrong: a live session flew to
# z = 2443 while the northernmost point sits at z = 661, and the table's slot
# still matched the player exactly (0.0 units).  The extent check rejected a
# demonstrably live table and closed navigation.  Slot agreement alone already
# separates live from stale -- 0.0 units against 22 to 49 -- so this remains
# only as a diagnostic helper.
TABLE_EXTENT_MARGIN = 1_500.0


def table_player_slot(table_address: int) -> int:
    return table_address + PLAYER_OFFSET_FROM_TABLE


def locations_contain(
    locations: Iterable[Location],
    player: tuple[float, float, float],
    margin: float = TABLE_EXTENT_MARGIN,
) -> bool:
    """Whether the player lies within this map's own extent.

    Diagnostic only -- see TABLE_EXTENT_MARGIN.  Players routinely fly far
    outside the region their destinations occupy, so this must not gate
    navigation.
    """
    points = list(locations)
    if not points:
        return False
    min_x = min(point.x for point in points) - margin
    max_x = max(point.x for point in points) + margin
    min_z = min(point.z for point in points) - margin
    max_z = max(point.z for point in points) + margin
    return min_x <= player[0] <= max_x and min_z <= player[2] <= max_z


def _planar_distance(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    return math.hypot(first[0] - second[0], first[2] - second[2])


# A player displacement smaller than this says nothing about whether the slot
# follows, so the verdict is carried over instead of being re-derived from noise.
LIVENESS_MOVEMENT_EPSILON = 4.0
# A following slot need not match the player's displacement exactly -- it is
# smoothed and offset -- but a frozen one covers none of it.
LIVENESS_TRACKING_FRACTION = 0.5


class LivenessTracker:
    """Decides whether a table's player slot follows the live player.

    Kept per session because the question is about motion over time, which a
    single frame cannot answer.  Verdicts latch: once movement has shown the
    slot following, a stationary player does not undo it, and once movement has
    shown it frozen, the table stays rejected until it starts following again.
    """

    def __init__(self) -> None:
        self._last: dict[int, tuple] = {}
        self._verdict: dict[int, bool] = {}

    def verdict_for(self, address: int) -> bool | None:
        return self._verdict.get(address)

    def observe(
        self,
        address: int,
        player: tuple[float, float, float],
        slot: tuple[float, float, float],
        tolerance: float = TABLE_LIVENESS_TOLERANCE,
    ) -> bool:
        previous = self._last.get(address)
        self._last[address] = (player, slot)

        if _planar_distance(slot, player) <= tolerance:
            self._verdict[address] = True
            return True

        if previous is not None:
            player_moved = _planar_distance(previous[0], player)
            if player_moved >= LIVENESS_MOVEMENT_EPSILON:
                slot_moved = _planar_distance(previous[1], slot)
                verdict = slot_moved >= player_moved * LIVENESS_TRACKING_FRACTION
                self._verdict[address] = verdict
                return verdict

        # The player is holding still, so motion cannot decide.  Keep whatever
        # motion last proved; with nothing proved, fall back to distance.
        settled = self._verdict.get(address)
        if settled is not None:
            return settled
        return False


def table_is_live(
    memory: MemoryView,
    table_address: int,
    locations: Iterable[Location],
    player: tuple[float, float, float],
    tolerance: float = TABLE_LIVENESS_TOLERANCE,
    tracker: "LivenessTracker | None" = None,
) -> bool:
    """Whether this table describes the surface the player is currently on.

    Decided by whether the table's own player slot follows the live player.
    Without a ``tracker`` there is no motion history, so the question collapses
    to whether the slot is sitting on the player right now.  ``locations`` is
    accepted for call-site symmetry and is not used.
    """
    slot = table_player_slot(table_address)
    # Not every map keeps a player slot beside its table.  The 0x500 offset was
    # derived from Earth, whose eight records are followed by one; a live map
    # with six records has nothing there at all -- a search of the 128 KiB
    # around its table found no triple matching the player.  Requiring the slot
    # therefore rejected every table that was not laid out like Earth's, which
    # is precisely the "it assumes Earth" failure.
    #
    # Absence is not evidence of staleness.  With no slot there is nothing to
    # disprove the table with, so it stands on its structural signature, which
    # is strict enough to have produced no false positives across ~950 MiB.  A
    # table that *does* carry a slot is still held to it.
    if not player_transform_is_valid(memory, slot):
        return True
    values = read_floats(memory, slot, 3)
    if values is None:
        return True
    reading = (values[0], values[1], values[2])
    if tracker is not None:
        return tracker.observe(table_address, player, reading, tolerance)
    return _planar_matches(reading, player, tolerance)


# --- Local-area entities ----------------------------------------------------
# Walking areas publish no coordinate table -- the only one in memory while
# standing in one is the previous world map's, gone stale.  What they do
# publish is a pool of 4x4 actor transforms, and a live scan showed those
# collapse into a small number of distinct positions: one cluster per character
# in the scene, each holding that character's bones.  Clustering the pool
# therefore enumerates the things worth walking to, entirely from RAM.

LOCAL_ENTITY_BLOCK = 0x00E20000
LOCAL_ENTITY_BLOCK_SIZE = 0x60000
LOCAL_ENTITY_STEP = 0x10
# Clustering is horizontal on purpose.  A character's bones span roughly 16
# units vertically -- a live scan read one figure's joints from y = 0 down to
# y = -16 -- so a 3D radius split a single NPC into eight "entities", while
# horizontally those same bones sit within a couple of units of each other.
LOCAL_ENTITY_CLUSTER_RADIUS = 8.0
# A cluster needs some bulk to be a character rather than a stray matrix.
MIN_LOCAL_ENTITY_TRANSFORMS = 4
# Anything this close to the player is the player's own model.
LOCAL_SELF_RADIUS = 8.0
LOCAL_ENTITY_RADIUS = 3.0
MAX_LOCAL_ENTITIES = 12


@dataclass(frozen=True)
class LocalEntity:
    """A character or object standing in a walking area."""

    address: int
    x: float
    y: float
    z: float
    transforms: int

    @property
    def position(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


def find_local_entities(
    block: bytes,
    base: int,
    player: tuple[float, float, float],
) -> tuple[LocalEntity, ...]:
    """Cluster the actor transform pool into one entry per entity.

    The player's own model is excluded: it is simply the cluster sitting on top
    of the player.  The representative address of each remaining cluster can be
    read live afterwards, so the expensive scan happens once per area rather
    than every tick.
    """
    view = FlatMemory(base, block)
    clusters: list[dict] = []
    for offset in range(0, len(block) - 0x40, LOCAL_ENTITY_STEP):
        address = base + offset
        parsed = parse_transform(view, address)
        if parsed is None:
            continue
        position = parsed[1]
        if not all(math.isfinite(value) for value in position):
            continue
        if max(abs(value) for value in position) >= 100_000.0:
            continue
        for cluster in clusters:
            if (
                math.hypot(
                    position[0] - cluster["position"][0],
                    position[2] - cluster["position"][2],
                )
                < LOCAL_ENTITY_CLUSTER_RADIUS
            ):
                cluster["count"] += 1
                # Keep the highest transform as the representative: it is the
                # figure's root rather than a foot or a hand.
                if position[1] > cluster["position"][1]:
                    cluster["position"] = position
                    cluster["address"] = address
                break
        else:
            clusters.append(
                {"position": position, "count": 1, "address": address}
            )

    entities = [
        LocalEntity(
            cluster["address"],
            cluster["position"][0],
            cluster["position"][1],
            cluster["position"][2],
            cluster["count"],
        )
        for cluster in clusters
        if cluster["count"] >= MIN_LOCAL_ENTITY_TRANSFORMS
        and math.hypot(
            cluster["position"][0] - player[0],
            cluster["position"][2] - player[2],
        )
        > LOCAL_SELF_RADIUS
    ]
    entities.sort(key=lambda entity: -entity.transforms)
    return tuple(entities[:MAX_LOCAL_ENTITIES])
