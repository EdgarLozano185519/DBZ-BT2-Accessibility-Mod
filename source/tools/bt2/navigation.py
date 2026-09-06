"""Cardinal navigation cues.

The Dragon Adventure overworld camera does not rotate, so world axes map to
fixed screen directions.  Which way is which was measured rather than assumed:
two paired RAM/screenshot captures put map point 3 at world (811, 275) drawn at
screen (411, 643), and point 5 at world (1645, -1656) drawn at (461, 739).
Increasing X moves right and increasing Z moves *up*, so:

    East  = +X        North = +Z
    West  = -X        South = -Z

Cues are emitted in a fixed structure so they read identically every time.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Node kinds this mod can actually distinguish.  Deliberately short: the game
# does not publish a type for a destination, so anything beyond these would be
# invented.  "story" and "free" appear only once the player has recorded what a
# destination turned out to be.
KIND_UNKNOWN = "unknown"
KIND_STORY = "story"
KIND_FREE = "free"
KIND_CHARACTER = "npc"

# Compass points, clockwise from north.
_COMPASS = (
    ("North", "north"),
    ("Northeast", "northeast"),
    ("East", "east"),
    ("Southeast", "southeast"),
    ("South", "south"),
    ("Southwest", "southwest"),
    ("West", "west"),
    ("Northwest", "northwest"),
)

# Distances are in the game's own world units.  They are not metres and no
# conversion is known -- the Earth map spans about 3700 of them -- so calling
# them metres would be inventing a scale.
UNIT_NAME = "units"

APPROACHING_DISTANCE = 20.0


def cardinal(delta_x: float, delta_z: float) -> tuple[str, str]:
    """Return (Title, spoken) compass names for a world-space offset."""
    if delta_x == 0.0 and delta_z == 0.0:
        return ("Here", "here")
    # atan2(east, north) puts 0 at north and increases clockwise.
    angle = math.degrees(math.atan2(delta_x, delta_z)) % 360.0
    index = int((angle + 22.5) // 45.0) % 8
    return _COMPASS[index]


@dataclass(frozen=True)
class Cue:
    """One navigation instruction, in the fixed output structure."""

    node_id: str
    node_type: str
    direction: str
    spoken_direction: str
    distance: float
    arrived: bool = False
    approaching: bool = False

    @property
    def instruction(self) -> str:
        if self.arrived:
            return f"Event reached. {self.node_id} is here."
        if self.approaching:
            return (
                f"Approaching {self.node_id}, "
                f"{self.distance:.0f} {UNIT_NAME} {self.spoken_direction}."
            )
        return (
            f"Fly {self.spoken_direction} for {self.distance:.0f} "
            f"{UNIT_NAME} toward {self.node_id}."
        )

    def block(self) -> str:
        return (
            f"TARGET: {self.node_id} ({self.node_type})\n"
            f"DIRECTION: {self.direction}\n"
            f"DISTANCE: {self.distance:.0f} {UNIT_NAME}\n"
            f"INSTRUCTION: {self.instruction}"
        )


def cue_for(
    player: tuple[float, float, float],
    target,
    node_id: str,
    node_type: str = KIND_UNKNOWN,
    arrived_within: float = 10.0,
) -> Cue:
    """Build a cue from the player's world position toward a target."""
    delta_x = target.x - player[0]
    delta_z = target.z - player[2]
    distance = math.hypot(delta_x, delta_z)
    direction, spoken = cardinal(delta_x, delta_z)
    return Cue(
        node_id=node_id,
        node_type=node_type,
        direction=direction,
        spoken_direction=spoken,
        distance=distance,
        arrived=distance <= arrived_within,
        approaching=arrived_within < distance <= APPROACHING_DISTANCE,
    )


def kind_from_profile(profile, index: int, is_local: bool) -> str:
    """Translate what the player recorded into a node type."""
    if is_local:
        return KIND_CHARACTER
    recorded = profile.kind_of(index)
    if recorded == profile.KIND_STORY:
        return KIND_STORY
    if recorded == profile.KIND_FREE:
        return KIND_FREE
    return KIND_UNKNOWN


# --- Solving a map's projection from accumulated markers --------------------
# Measured live: four markers fit an affine to 1.07 px, so the world-to-screen
# relationship *is* affine -- an earlier 33 px figure came from hand-measured
# anchors carrying their own error, not from the map being curved.
#
# What defeats matching is the number of markers drawn at once. The game shows
# only the currently available destinations; a completed save still showed five
# of eight, and five against eight leaves the assignment ambiguous (runner-up
# only 1.09x worse). Marker positions are stable per map, so accumulating them
# across chapters approaches the full set, at which point the assignment becomes
# unique and the projection can be solved once and kept.

# From simulation over the real Earth geometry: with accurate markers the true
# assignment wins by a wide margin, so anything less is not trustworthy.
ASSIGNMENT_MIN_MARGIN = 2.0
ASSIGNMENT_MAX_RESIDUAL = 4.0
ASSIGNMENT_MIN_MARKERS = 6
ASSIGNMENT_MAX_MARKERS = 8


def _fit_affine(rows, target):
    """Least-squares fit of one affine row, in plain arithmetic.

    A three-parameter fit is the 3x3 normal equations, which Cramer's rule
    solves outright, so the search stays in plain arithmetic instead of making
    tens of thousands of ``numpy.linalg`` calls on three-column systems.
    Returns ``None`` for a singular system rather than raising.

    Note on what this did *not* fix: the suite segfaults intermittently inside
    this function, and rewriting it away from ``lstsq`` and then away from
    ``solve`` did not stop it.  The fault handler puts the crash in
    "Garbage-collecting", which points at heap corruption from somewhere else
    being tripped over here rather than at this arithmetic.  This version is
    kept because it is simpler and dependency-free, not because it is a fix.
    """
    normal = [[0.0] * 3 for _ in range(3)]
    moment = [0.0] * 3
    for (a, b, c), value in zip(rows, target):
        row = (a, b, c)
        for i in range(3):
            moment[i] += row[i] * value
            for j in range(3):
                normal[i][j] += row[i] * row[j]

    def determinant(m):
        return (
            m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
            - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
            + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
        )

    base = determinant(normal)
    if abs(base) < 1e-9:
        return None
    result = []
    for column in range(3):
        swapped = [list(row) for row in normal]
        for row_index in range(3):
            swapped[row_index][column] = moment[row_index]
        result.append(determinant(swapped) / base)
    return result


def _residual(rows, coefficients_x, coefficients_y, target_x, target_y):
    worst = 0.0
    for (a, b, c), want_x, want_y in zip(rows, target_x, target_y):
        got_x = a * coefficients_x[0] + b * coefficients_x[1] + c * coefficients_x[2]
        got_y = a * coefficients_y[0] + b * coefficients_y[1] + c * coefficients_y[2]
        worst = max(worst, math.hypot(got_x - want_x, got_y - want_y))
    return worst


def solve_map_affine(world, screens):
    """Assign screen markers to world points and solve the projection.

    ``world`` is a sequence of (x, z); ``screens`` a sequence of (px, py).
    Returns ``(coefficients, residual, margin, assignment)`` or ``None`` when
    the answer is not unique enough to act on.
    """
    import itertools

    if not (ASSIGNMENT_MIN_MARKERS <= len(screens) <= ASSIGNMENT_MAX_MARKERS):
        return None
    if len(world) < len(screens) or len(world) > ASSIGNMENT_MAX_MARKERS:
        return None

    target_x = [float(s[0]) for s in screens]
    target_y = [float(s[1]) for s in screens]
    results = []
    for chosen in itertools.permutations(range(len(world)), len(screens)):
        rows = [(float(world[i][0]), float(world[i][1]), 1.0) for i in chosen]
        fit_x = _fit_affine(rows, target_x)
        fit_y = _fit_affine(rows, target_y)
        if fit_x is None or fit_y is None:
            continue
        results.append(
            (_residual(rows, fit_x, fit_y, target_x, target_y), chosen, fit_x, fit_y)
        )
    if not results:
        return None
    results.sort(key=lambda item: item[0])

    best, chosen, fit_x, fit_y = results[0]
    runner_up = results[1][0] if len(results) > 1 else float("inf")
    margin = runner_up / max(best, 1e-9)
    if best > ASSIGNMENT_MAX_RESIDUAL or margin < ASSIGNMENT_MIN_MARGIN:
        return None
    coefficients = [float(v) for v in (*fit_x, *fit_y)]
    return coefficients, best, margin, chosen


def project_with(coefficients, x: float, z: float) -> tuple[float, float]:
    """Apply a solved map affine to a world position."""
    a, b, c, d, e, f = coefficients
    return (a * x + b * z + c, d * x + e * z + f)


def unproject_with(coefficients, screen_x: float, screen_y: float):
    """Read a world position back out of a screen position.

    This is what lets a marker be navigated to without a matching table entry.
    The story objective turned out not to be in the coordinate table at all --
    on a live map its marker sat 41 px from the nearest point and 45 from the
    next, on opposite sides of each, with no linear fit placing it on either --
    so the table can name free events but never the objective.  Inverting the
    projection gives the marker its own world coordinates directly.

    Returns ``None`` when the projection is degenerate or has rotation, which
    this inverse does not handle.
    """
    a, b, c, d, e, f = coefficients
    if b or d:
        return None
    if not a or not e:
        return None
    return ((screen_x - c) / a, (screen_y - f) / e)
