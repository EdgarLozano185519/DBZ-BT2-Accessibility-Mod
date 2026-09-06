"""Automatic, near-instant calibration of the world-to-HUD relationship.

Why this is not a global map fit
--------------------------------
The obvious model -- one affine transform per map, solved from many spread-out
observations -- does not actually describe this game.  Fitting the eight Earth
map points against their measured screen positions leaves a 35-pixel worst-case
residual, and a projective (homography) model does no better.  The world-to-HUD
relationship is globally nonlinear.

But it is locally smooth, and the game gives us a free anchor: the player arrow.
Its world position is known exactly from RAM and its screen position is
directly observable, so the *translation* term never has to be estimated -- it
is re-read every frame.  All that remains is the 2x2 Jacobian: how many screen
units one world unit is worth, and in which direction.

That reformulation is what removes manual calibration.  A global six-parameter
fit needs many well-separated samples before it is trustworthy.  A Jacobian
needs two movements in different directions, which normal play produces in
about a second, and it is re-anchored on the arrow every frame so it stays
accurate even where a global fit would drift.

The Jacobian is a property of the map, so it is saved per map fingerprint.  The
second visit to a map is calibrated the instant the arrow is found.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# A delta must move the player far enough that the arrow visibly moved.  The
# HUD scale is roughly 0.00004 normalized units per world unit, so 80 world
# units is about 5 pixels at 1330x880 -- comfortably above detection noise.
MIN_DELTA_WORLD = 80.0
# Two nearly parallel movements cannot separate the Jacobian's columns.
MIN_DIRECTION_SPREAD_DEGREES = 20.0
MIN_DELTAS = 2
MAX_DELTAS = 48
# A delta whose reprojection is this far off is a bad arrow detection.
DELTA_INLIER_TOLERANCE = 0.004
# Two deltas give four equations for four unknowns, so the fit is exactly
# determined and its residual is identically zero however wrong the inputs are.
# A live session proved this: two bad arrow detections produced a "perfect"
# error of 1.2e-16 and a scale 23x too large, which was then saved as trusted.
# Three deltas over-determine the system, so the residual means something.
MIN_INLIER_DELTAS = 3
# Beyond that, hold each delta out and check the rest predict it.  This catches
# consistently-wrong detections that a plain residual cannot see.
CROSS_VALIDATION_MIN_DELTAS = 4
CROSS_VALIDATION_TOLERANCE = 0.006
# Sanity band for the HUD scale, in normalized screen units per world unit.
MIN_PLAUSIBLE_SCALE = 2.0e-6
MAX_PLAUSIBLE_SCALE = 2.0e-3


@dataclass(frozen=True)
class Delta:
    """One observed movement: world displacement and screen displacement."""

    world_x: float
    world_z: float
    screen_x: float
    screen_y: float

    @property
    def world_length(self) -> float:
        return math.hypot(self.world_x, self.world_z)

    @property
    def direction(self) -> float:
        return math.atan2(self.world_z, self.world_x)


@dataclass(frozen=True)
class Jacobian:
    """d(screen)/d(world), in normalized screen units per world unit."""

    xx: float
    xz: float
    yx: float
    yz: float

    def apply(self, world_x: float, world_z: float) -> tuple[float, float]:
        return (
            self.xx * world_x + self.xz * world_z,
            self.yx * world_x + self.yz * world_z,
        )

    @property
    def determinant(self) -> float:
        return self.xx * self.yz - self.xz * self.yx

    @property
    def scale(self) -> float:
        return math.sqrt(abs(self.determinant))

    @property
    def plausible(self) -> bool:
        return MIN_PLAUSIBLE_SCALE <= self.scale <= MAX_PLAUSIBLE_SCALE

    def invert(self) -> "Jacobian | None":
        determinant = self.determinant
        if abs(determinant) < 1e-18:
            return None
        return Jacobian(
            self.yz / determinant,
            -self.xz / determinant,
            -self.yx / determinant,
            self.xx / determinant,
        )

    def as_list(self) -> list[float]:
        return [self.xx, self.xz, self.yx, self.yz]

    @classmethod
    def from_list(cls, values) -> "Jacobian":
        return cls(*(float(value) for value in values))


@dataclass(frozen=True)
class AnchoredProjection:
    """A projection pinned to the live arrow, valid around the player.

    ``player`` is the current world position and ``anchor`` is where the arrow
    was seen for it, both refreshed every frame.  Only the Jacobian is learned.
    """

    jacobian: Jacobian
    player: tuple[float, float]
    anchor: tuple[float, float]

    def project(self, world_x: float, world_z: float) -> tuple[float, float]:
        offset_x, offset_y = self.jacobian.apply(
            world_x - self.player[0], world_z - self.player[1]
        )
        return self.anchor[0] + offset_x, self.anchor[1] + offset_y

    def project_to_window(
        self, world_x: float, world_z: float, width: int, height: int
    ) -> tuple[float, float]:
        normalized_x, normalized_y = self.project(world_x, world_z)
        return normalized_x * width, normalized_y * height

    def world_bearing(
        self, screen_dx: float, screen_dy: float
    ) -> tuple[float, float] | None:
        """Convert a screen offset into the world direction that achieves it."""
        inverse = self.jacobian.invert()
        if inverse is None:
            return None
        return inverse.apply(screen_dx, screen_dy)


@dataclass(frozen=True)
class Calibration:
    jacobian: Jacobian
    delta_count: int
    inlier_count: int
    spread_degrees: float
    median_error: float
    cross_validation_error: float | None = None

    @property
    def confident(self) -> bool:
        if self.inlier_count < MIN_INLIER_DELTAS:
            return False
        if self.spread_degrees < MIN_DIRECTION_SPREAD_DEGREES:
            return False
        if not self.jacobian.plausible:
            return False
        if self.median_error > DELTA_INLIER_TOLERANCE:
            return False
        if self.cross_validation_error is not None:
            return self.cross_validation_error <= CROSS_VALIDATION_TOLERANCE
        return True

    def describe(self) -> str:
        detail = (
            f"{self.inlier_count} movements spanning "
            f"{self.spread_degrees:.0f} degrees"
        )
        if self.cross_validation_error is not None:
            detail += f", cross-checked to {self.cross_validation_error * 100:.2f}%"
        return detail


def _direction_spread(deltas) -> float:
    """Largest angle between any two movement directions, in degrees."""
    best = 0.0
    directions = [delta.direction for delta in deltas]
    for index, first in enumerate(directions):
        for second in directions[index + 1 :]:
            difference = abs(first - second) % (2.0 * math.pi)
            if difference > math.pi:
                difference = 2.0 * math.pi - difference
            # Opposite directions are just as useless as identical ones for
            # separating the columns, so fold onto 0..90 degrees.
            if difference > math.pi / 2.0:
                difference = math.pi - difference
            best = max(best, difference)
    return math.degrees(best)


def solve_jacobian(deltas) -> Jacobian | None:
    """Least squares over ``screen_delta = J . world_delta``."""
    if len(deltas) < MIN_DELTAS:
        return None
    sum_xx = sum_xz = sum_zz = 0.0
    for delta in deltas:
        sum_xx += delta.world_x * delta.world_x
        sum_xz += delta.world_x * delta.world_z
        sum_zz += delta.world_z * delta.world_z
    determinant = sum_xx * sum_zz - sum_xz * sum_xz
    if abs(determinant) < 1e-9:
        return None

    def solve_row(screen_of) -> tuple[float, float]:
        right_x = right_z = 0.0
        for delta in deltas:
            value = screen_of(delta)
            right_x += delta.world_x * value
            right_z += delta.world_z * value
        return (
            (sum_zz * right_x - sum_xz * right_z) / determinant,
            (sum_xx * right_z - sum_xz * right_x) / determinant,
        )

    xx, xz = solve_row(lambda delta: delta.screen_x)
    yx, yz = solve_row(lambda delta: delta.screen_y)
    return Jacobian(xx, xz, yx, yz)


def delta_residuals(jacobian: Jacobian, deltas) -> list[float]:
    errors = []
    for delta in deltas:
        screen_x, screen_y = jacobian.apply(delta.world_x, delta.world_z)
        errors.append(
            math.hypot(screen_x - delta.screen_x, screen_y - delta.screen_y)
        )
    return errors


def _cross_validation_error(deltas) -> float | None:
    """Median leave-one-out prediction error, or None if there is too little data.

    Fitting and scoring on the same movements cannot detect a detection error
    that is self-consistent.  Predicting a movement the fit never saw can.
    """
    if len(deltas) < CROSS_VALIDATION_MIN_DELTAS:
        return None
    errors = []
    for index in range(len(deltas)):
        others = deltas[:index] + deltas[index + 1 :]
        model = solve_jacobian(others)
        if model is None:
            continue
        held_out = deltas[index]
        screen_x, screen_y = model.apply(held_out.world_x, held_out.world_z)
        errors.append(
            math.hypot(
                screen_x - held_out.screen_x, screen_y - held_out.screen_y
            )
        )
    if not errors:
        return None
    errors.sort()
    middle = len(errors) // 2
    if len(errors) % 2:
        return errors[middle]
    return (errors[middle - 1] + errors[middle]) / 2.0


@dataclass
class Calibrator:
    """Learns one map's Jacobian from movements observed during normal play."""

    fingerprint: str
    deltas: list[Delta] = field(default_factory=list)
    calibration: Calibration | None = None
    _last_world: tuple[float, float] | None = None
    _last_screen: tuple[float, float] | None = None

    def observe(
        self,
        world_x: float,
        world_z: float,
        screen_x: float,
        screen_y: float,
    ) -> bool:
        """Record where the arrow was for a world position.

        Returns whether this observation completed a usable movement delta.
        """
        if not all(
            math.isfinite(value)
            for value in (world_x, world_z, screen_x, screen_y)
        ):
            return False
        world = (world_x, world_z)
        screen = (screen_x, screen_y)
        previous_world = self._last_world
        previous_screen = self._last_screen
        self._last_world = world
        self._last_screen = screen
        if previous_world is None or previous_screen is None:
            return False

        delta = Delta(
            world[0] - previous_world[0],
            world[1] - previous_world[1],
            screen[0] - previous_screen[0],
            screen[1] - previous_screen[1],
        )
        if delta.world_length < MIN_DELTA_WORLD:
            # Not enough movement to be informative; keep the earlier anchor so
            # a slow drift still accumulates into a usable delta.
            self._last_world = previous_world
            self._last_screen = previous_screen
            return False
        self.deltas.append(delta)
        if len(self.deltas) > MAX_DELTAS:
            self.deltas.pop(0)
        self.solve()
        return True

    def reset_anchor(self) -> None:
        """Forget the previous frame, e.g. after a teleport or a load."""
        self._last_world = None
        self._last_screen = None

    @property
    def last_screen(self) -> tuple[float, float] | None:
        """Where this track was last seen, for the stationary drift test."""
        return self._last_screen

    def note_screen(self, screen: tuple[float, float]) -> None:
        """Record a screen position without forming a movement delta.

        Used for frames where the player did not move: the position still
        matters for detecting drift, but the pair carries no information about
        the Jacobian and must not be fed to the solver.
        """
        self._last_screen = screen

    def solve(self) -> Calibration | None:
        if len(self.deltas) < MIN_DELTAS:
            return self.calibration
        candidate = solve_jacobian(self.deltas)
        if candidate is None:
            return self.calibration

        errors = delta_residuals(candidate, self.deltas)
        inliers = [
            delta
            for delta, error in zip(self.deltas, errors)
            if error <= DELTA_INLIER_TOLERANCE
        ]
        if len(inliers) >= MIN_INLIER_DELTAS and len(inliers) < len(self.deltas):
            refined = solve_jacobian(inliers)
            if refined is not None:
                candidate = refined
                errors = delta_residuals(candidate, inliers)
        else:
            inliers = list(self.deltas)

        ordered = sorted(errors)
        middle = len(ordered) // 2
        median = (
            ordered[middle]
            if len(ordered) % 2
            else (ordered[middle - 1] + ordered[middle]) / 2.0
        ) if ordered else 0.0

        result = Calibration(
            jacobian=candidate,
            delta_count=len(self.deltas),
            inlier_count=len(inliers),
            spread_degrees=_direction_spread(inliers),
            median_error=median,
            cross_validation_error=_cross_validation_error(inliers),
        )
        if (
            self.calibration is not None
            and self.calibration.confident
            and not result.confident
        ):
            # A burst of bad detections must not undo a working calibration.
            return self.calibration
        self.calibration = result
        return self.calibration

    def seed(self, jacobian: Jacobian) -> None:
        """Adopt a Jacobian saved from an earlier visit.

        This is what makes a return visit instant: the stored value is the
        whole learned quantity, and the anchor comes free from the live arrow.
        """
        self.calibration = Calibration(
            jacobian=jacobian,
            delta_count=0,
            inlier_count=MIN_INLIER_DELTAS,
            spread_degrees=90.0,
            median_error=0.0,
        )

    def projection(
        self, player: tuple[float, float], anchor: tuple[float, float]
    ) -> AnchoredProjection | None:
        if self.calibration is None or not self.calibration.confident:
            return None
        return AnchoredProjection(self.calibration.jacobian, player, anchor)


# --- Flight altitude --------------------------------------------------------
# The coordinate table stores y = 0 for every Earth point, but the player flies
# the overworld at a resting altitude far below that -- every world capture in
# the corpus sits between -169 and -171.  Planar distance alone therefore says
# "you are on the point" while the player is hovering well off the plane where
# the game accepts the interaction.  The resting altitude is learned per map
# rather than hard-coded, so this works on a map that has never been visited.

# Normal flight wanders by about a unit; well below the ~16 units seen when a
# player is left hovering off-plane.
ALTITUDE_TOLERANCE = 6.0
MIN_ALTITUDE_SAMPLES = 8
MAX_ALTITUDE_SAMPLES = 120
# If the spread is wider than this the player is climbing or diving, not
# resting, and no single altitude describes the map yet.
MAX_ALTITUDE_SPREAD = 12.0


@dataclass
class AltitudeTracker:
    """Learns the altitude at which a map is normally flown."""

    samples: list[float] = field(default_factory=list)
    resting: float | None = None

    def observe(self, y: float) -> None:
        if not math.isfinite(y):
            return
        self.samples.append(y)
        if len(self.samples) > MAX_ALTITUDE_SAMPLES:
            self.samples.pop(0)
        if len(self.samples) < MIN_ALTITUDE_SAMPLES:
            return
        ordered = sorted(self.samples)
        # Trim the extremes so a climb or a dive cannot drag the estimate.
        trim = len(ordered) // 8
        core = ordered[trim : len(ordered) - trim] or ordered
        if core[-1] - core[0] > MAX_ALTITUDE_SPREAD:
            return
        middle = len(core) // 2
        self.resting = (
            core[middle]
            if len(core) % 2
            else (core[middle - 1] + core[middle]) / 2.0
        )

    def seed(self, altitude: float) -> None:
        self.resting = altitude

    @property
    def known(self) -> bool:
        return self.resting is not None

    def offset(self, y: float) -> float | None:
        """How far above (+) or below (-) the resting altitude the player is."""
        if self.resting is None:
            return None
        return y - self.resting

    def aligned(self, y: float) -> bool:
        offset = self.offset(y)
        return offset is None or abs(offset) <= ALTITUDE_TOLERANCE


# --- Identifying the arrow by correlation -----------------------------------
# Neither size nor "the only thing that moved" identifies the player arrow on
# the world map: a live capture had four drifting cloud blobs beside it, one of
# them larger.  What separates the arrow is that its screen motion is *caused*
# by player input.  Clouds drift while the player stands still and drift
# independently while the player moves, so a per-track Jacobian fits the arrow
# and fails everything else.

# Below this the player is treated as stationary for the drift test.
STATIONARY_WORLD = 6.0
# Drift is measured cumulatively from where the player stopped, not frame to
# frame: clouds move only about a pixel per sample, which is under any threshold
# that also tolerates detection jitter, but the displacement accumulates while
# the arrow's does not.  This is ~2.7 px at the captured HUD width.
STATIONARY_SCREEN_DRIFT = 0.002
# How many drift events disqualify a track outright.  More than one so a single
# spurious detection cannot permanently rule out the real arrow.
MAX_DRIFT_STRIKES = 2


@dataclass
class TrackCandidate:
    """One white HUD element being evaluated as the player arrow."""

    identifier: int
    calibrator: "Calibrator"
    drift_strikes: int = 0
    stationary_samples: int = 0
    stationary_origin: tuple[float, float] | None = None

    @property
    def disqualified(self) -> bool:
        return self.drift_strikes >= MAX_DRIFT_STRIKES

    @property
    def score(self) -> float:
        """Lower is better; infinite when the track cannot be the arrow."""
        if self.disqualified:
            return float("inf")
        calibration = self.calibrator.calibration
        if calibration is None or not calibration.confident:
            return float("inf")
        return calibration.median_error


class ArrowIdentifier:
    """Decides which tracked blob is the player arrow, and calibrates from it.

    Identification and calibration are the same computation: the arrow is the
    track whose movement is explained by a single plausible Jacobian, and that
    Jacobian is the calibration.
    """

    def __init__(self, fingerprint: str):
        self.fingerprint = fingerprint
        self.candidates: dict[int, TrackCandidate] = {}
        self._last_world: tuple[float, float] | None = None

    def observe(
        self,
        player: tuple[float, float],
        positions: dict[int, tuple[float, float]],
    ) -> None:
        """Feed one frame: the player's world position and each track's screen position."""
        previous_world = self._last_world
        self._last_world = player
        stationary = (
            previous_world is not None
            and math.hypot(
                player[0] - previous_world[0], player[1] - previous_world[1]
            ) < STATIONARY_WORLD
        )

        for identifier, screen in positions.items():
            candidate = self.candidates.get(identifier)
            if candidate is None:
                candidate = TrackCandidate(
                    identifier, Calibrator(f"{self.fingerprint}:{identifier}")
                )
                self.candidates[identifier] = candidate

            if stationary:
                # The decisive test.  The arrow cannot move while the player
                # does not; a drifting cloud can and does.  Measured against
                # where this track was when the player stopped, so slow drift
                # accumulates into a verdict instead of hiding under the noise
                # floor every single frame.
                if candidate.stationary_origin is None:
                    candidate.stationary_origin = screen
                else:
                    origin = candidate.stationary_origin
                    drift = math.hypot(
                        screen[0] - origin[0], screen[1] - origin[1]
                    )
                    if drift > STATIONARY_SCREEN_DRIFT:
                        candidate.drift_strikes += 1
                        # Re-origin so continued drift keeps scoring rather
                        # than counting the same displacement forever.
                        candidate.stationary_origin = screen
                candidate.stationary_samples += 1
                candidate.calibrator.note_screen(screen)
                continue

            candidate.stationary_origin = None

            if not candidate.disqualified:
                candidate.calibrator.observe(player[0], player[1], screen[0], screen[1])

        # Tracks that vanished are dropped by the caller's tracker; mirror that.
        for identifier in list(self.candidates):
            if identifier not in positions:
                self.candidates[identifier].calibrator.reset_anchor()

    def best(self) -> TrackCandidate | None:
        """The single qualifying track, or None while the answer is ambiguous."""
        qualified = [
            candidate
            for candidate in self.candidates.values()
            if candidate.score < float("inf")
        ]
        if len(qualified) != 1:
            return None
        return qualified[0]

    @property
    def calibration(self) -> Calibration | None:
        winner = self.best()
        return winner.calibrator.calibration if winner else None

    def describe(self) -> str:
        total = len(self.candidates)
        drifted = sum(1 for c in self.candidates.values() if c.disqualified)
        solving = sum(
            1
            for c in self.candidates.values()
            if not c.disqualified and c.calibrator.deltas
        )
        return (
            f"{total} white tracks, {drifted} ruled out by drift, "
            f"{solving} accumulating movement"
        )


# --- Anchoring without the arrow --------------------------------------------
# Once the scale is known the projection still needs an anchor, and finding the
# arrow in a single frame is not possible: it is not the largest white element
# and only its response to player movement distinguishes it from the map's
# clouds.  But the markers already on screen are anchors too.  For the correct
# marker-to-point assignment every pair implies the *same* anchor, so the
# answer is the position that the most pairs agree on.

# Two anchors within this distance (normalized) are treated as agreeing.
ANCHOR_CLUSTER_TOLERANCE = 0.01
# Three agreeing markers, not two.  The Jacobian is a *local* linearization and
# the world-to-HUD relationship is not globally linear, so markers far from the
# player do not fit it.  A live frame with the player far east had only two of
# four markers agree, which is too little to act on.
MIN_ANCHOR_VOTES = 3


def anchor_from_markers(
    jacobian: Jacobian,
    markers,
    locations,
    player: tuple[float, float],
) -> tuple[float, float] | None:
    """Recover the projection anchor by voting over marker/point pairs.

    ``markers`` are normalized screen positions, ``locations`` carry world
    coordinates, and ``player`` is the live world position.  Returns ``None``
    when no position commands a clear majority, which is the honest answer for
    an ambiguous frame.
    """
    if not markers or not locations:
        return None

    candidates: list[tuple[float, float]] = []
    for screen_x, screen_y in markers:
        for location in locations:
            offset_x, offset_y = jacobian.apply(
                location.x - player[0], location.z - player[1]
            )
            candidates.append((screen_x - offset_x, screen_y - offset_y))

    best_votes: list[tuple[float, float]] = []
    for candidate in candidates:
        votes = [
            other
            for other in candidates
            if math.hypot(other[0] - candidate[0], other[1] - candidate[1])
            <= ANCHOR_CLUSTER_TOLERANCE
        ]
        if len(votes) > len(best_votes):
            best_votes = votes

    if len(best_votes) < MIN_ANCHOR_VOTES:
        return None
    # A marker can only vote once for the true anchor, so a cluster larger than
    # the marker count means several points are being conflated.
    if len(best_votes) > len(markers):
        return None
    return (
        sum(vote[0] for vote in best_votes) / len(best_votes),
        sum(vote[1] for vote in best_votes) / len(best_votes),
    )
