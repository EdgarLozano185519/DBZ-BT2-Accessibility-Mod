"""Teach a map's minimap-to-world scale with commanded teleports.

Why this exists
---------------
``calibration.Calibrator`` learns the Jacobian from movement observed during
normal play, which means flying.  The player this mod is for cannot fly --
movement is unpredictable without sight, so teleport is not a convenience here
but the primary way to travel.  That left the scale unlearnable on every map,
and the scale is exactly what converts the story marker's minimap pixels into
coordinates teleport can write.  The one destination that matters was the one
destination T could not reach.

Teleport is movement the guide commands.  Six short paused hops, each a known
world displacement, produce precisely the observations the Jacobian needs, and
the last hop is the trip home, so the player finishes where they began.

What this does not do
---------------------
It does not re-derive the maths or the thresholds.  ``solve_jacobian``,
``Calibration`` and its ``confident`` test are the ones incidental play already
uses, so a scale learned here is trusted on exactly the same evidence as a
scale learned by flying -- including the leave-one-out cross-check that exists
because two self-consistent bad detections once produced a "perfect" fit that
was 23x too large.

What it does own is the *correspondence*.  ``ArrowIdentifier`` decides which
white blob is the player arrow from how it drifts while the player stands
still, which needs the game running and the player moving under their own
power.  Here the blobs are matched across commanded hops instead, and the
arrow is the one track whose motion a single plausible Jacobian explains.  A
cloud drifts a pixel or two across the whole run, which fits a Jacobian far
below ``MIN_PLAUSIBLE_SCALE`` and is refused rather than believed.

Everything the player is asked to do is spoken, and nothing happens until they
have done it.  A run that fails puts them back where it found them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .calibration import (
    Calibration,
    Delta,
    MIN_DELTA_WORLD,
    _cross_validation_error,
    _direction_spread,
    delta_residuals,
    solve_jacobian,
)
from .markers import MarkerLocation

# Six hops: one probe out, one home, then a square.  The probe exists because
# the right hop size is a screen distance while the map's scale is the unknown
# being solved for -- so the first hop is deliberately cautious and the rest
# are sized from what it measured.
TOTAL_MOVES = 6

# Target arrow displacement per hop, in normalized screen units.  About 30 px
# at the 1330-wide capture these notes were written against: far above the
# 0.004 inlier tolerance that decides whether a delta is believed, and well
# inside the minimap panel so a hop cannot push the arrow against its edge,
# where the screen position stops tracking the world position at all.
TARGET_SCREEN_DELTA = 0.022
# A measured probe below this told us little; the hop size is then reached for
# rather than extrapolated from noise.
MIN_USEFUL_SCREEN_DELTA = 0.003
MAX_SCREEN_DELTA = 0.035

# A hop must clear this to be informative -- the shared floor from
# calibration.py with margin, because a hop shorter than it is discarded.
MIN_HOP_WORLD = MIN_DELTA_WORLD * 1.5
# Blobs this far apart between two samples are not the same blob.  Generous
# compared with the frame-to-frame tracker's 60 px, because consecutive samples
# here are a whole teleport apart rather than a quarter of a second.
MATCH_RADIUS = 0.055
# Landing this close to a destination risks entering it.  A calibration hop
# must never start a story event by accident.
DESTINATION_CLEARANCE = 1.35
# The arrow must be still before a sample is taken, or the sample pairs a world
# position with where the arrow was a moment earlier.
SETTLED_SCREEN_DRIFT = 0.004
SETTLE_SAMPLES = 2

# How often the guide repeats an instruction the player has not acted on yet.
REMINDER_SECONDS = 9.0
# A move nobody completes should not hold the guide for ever.
MOVE_TIMEOUT_SECONDS = 180.0

ARM = "arm"
WRITTEN = "written"
SETTLE = "settle"


@dataclass(frozen=True)
class Sample:
    """One resting observation: where the player is, and every white blob."""

    world: tuple[float, float]
    blobs: tuple[tuple[float, float], ...]


@dataclass
class _Track:
    positions: list = field(default_factory=list)


def match_tracks(samples) -> list:
    """Follow each white blob across every sample, dropping any that vanish.

    The player arrow is drawn on every world map frame, so a track absent from
    even one sample cannot be it.  Requiring presence throughout is what lets
    the match radius be generous without letting a track wander between blobs.
    """
    if not samples:
        return []
    tracks = [_Track([position]) for position in samples[0].blobs]
    for sample in samples[1:]:
        taken = set()
        survivors = []
        for track in tracks:
            last = track.positions[-1]
            best = None
            best_distance = None
            for index, position in enumerate(sample.blobs):
                if index in taken:
                    continue
                distance = math.hypot(
                    position[0] - last[0], position[1] - last[1]
                )
                if distance > MATCH_RADIUS:
                    continue
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best = index
            if best is None:
                continue
            taken.add(best)
            track.positions.append(sample.blobs[best])
            survivors.append(track)
        tracks = survivors
    return [track.positions for track in tracks]


def deltas_for(samples, positions) -> list:
    """Pair each hop's world displacement with one track's screen displacement."""
    deltas = []
    for index in range(1, len(samples)):
        world_before = samples[index - 1].world
        world_after = samples[index].world
        delta = Delta(
            world_after[0] - world_before[0],
            world_after[1] - world_before[1],
            positions[index][0] - positions[index - 1][0],
            positions[index][1] - positions[index - 1][1],
        )
        if delta.world_length < MIN_DELTA_WORLD:
            # The hop did not happen, or the player was put back on their own
            # position.  A delta the solver would weight at nothing.
            continue
        deltas.append(delta)
    return deltas


def calibration_from(deltas):
    """The shared solve, scored by the shared rules."""
    jacobian = solve_jacobian(deltas)
    if jacobian is None:
        return None
    errors = sorted(delta_residuals(jacobian, deltas))
    middle = len(errors) // 2
    if not errors:
        median = 0.0
    elif len(errors) % 2:
        median = errors[middle]
    else:
        median = (errors[middle - 1] + errors[middle]) / 2.0
    return Calibration(
        jacobian=jacobian,
        delta_count=len(deltas),
        inlier_count=len(deltas),
        spread_degrees=_direction_spread(deltas),
        median_error=median,
        cross_validation_error=_cross_validation_error(list(deltas)),
    )


def solve_from_samples(samples):
    """Return ``(result, None)`` for the one track that can be the arrow.

    ``result`` is ``(calibration, anchor)``, where the anchor is where that
    track sat in the final sample.  That is the live correspondence the
    projection needs, and nothing else can supply it once the player has
    stopped moving under their own power.

    Returns ``(None, reason)`` when the answer is not single and confident.
    Ambiguity is reported rather than resolved: two tracks that both fit means
    the run did not separate them, and picking one would be a guess wearing a
    measurement's clothes.
    """
    tracks = match_tracks(samples)
    if not tracks:
        return None, "the minimap arrow was not visible for the whole run"
    winners = []
    for positions in tracks:
        deltas = deltas_for(samples, positions)
        calibration = calibration_from(deltas)
        if calibration is not None and calibration.confident:
            winners.append((calibration, positions[-1]))
    if not winners:
        return None, "no white marker on the minimap moved the way the hops did"
    if len(winners) > 1:
        return None, (
            f"{len(winners)} minimap markers fit the hops equally well, so the "
            "arrow could not be told apart"
        )
    return winners[0], None


# With no table -- or one point, which has no extent -- the hops are planned
# inside a square of this half-width around the player.  Every map measured so
# far spans 3000 to 4000 units, so this sizes the probe the same way a table
# would, without knowing where the map's edges are.  A player near an edge is
# still protected: an arrow pinned against the panel gives inconsistent deltas,
# and the cross-check refuses those.
DEFAULT_HALF_SPAN = 2000.0


def map_bounds(locations, home=None):
    """The coordinate table's own extent, which is the map the arrow is drawn on.

    Falls back to a fixed square around ``home`` when the table cannot supply
    one; None only when neither is available.
    """
    if len(locations) >= 2:
        xs = [location.x for location in locations]
        zs = [location.z for location in locations]
        return (min(xs), min(zs), max(xs), max(zs))
    if home is None:
        return None
    return (
        home[0] - DEFAULT_HALF_SPAN,
        home[1] - DEFAULT_HALF_SPAN,
        home[0] + DEFAULT_HALF_SPAN,
        home[1] + DEFAULT_HALF_SPAN,
    )


def clear_of_destinations(point, locations) -> bool:
    """Whether a landing sits outside every destination's trigger volume."""
    for location in locations:
        reach = location.radius * DESTINATION_CLEARANCE
        if math.hypot(point[0] - location.x, point[1] - location.z) <= reach:
            return False
    return True


def choose_quadrant(home, locations, reach):
    """Which way to hop so every waypoint stays on the map and out of trouble.

    Returns ``(quadrant, None)``, or ``(None, reason)`` naming what got in the
    way, so a refusal can tell the player something they can act on.

    Hops go into one quadrant around the player rather than in all directions,
    so a player already near the edge of the map is moved inward.  A waypoint
    outside the map pins the arrow against the edge of the minimap panel, where
    it stops moving while the world position keeps changing -- a false
    correspondence that would be solved into a wrong scale rather than refused.

    **Where the player already stands is exempt from the destination check.**
    Teleporting onto a destination and pressing the action button is how this
    mod's player crosses a map, so that is exactly where they will be when they
    reach for calibration -- and standing on one is safe, because the game
    enters an event on the action button rather than on arrival.  Requiring the
    home corner to be clear refused the first real attempt at the one spot the
    player was most likely to be: dead centre of point 7, where a teleport had
    just put them, with every hop size blocked by the place they were standing.
    """
    bounds = map_bounds(locations, home)
    margin_x = (bounds[2] - bounds[0]) * 0.05
    margin_z = (bounds[3] - bounds[1]) * 0.05
    reasons = []
    for sign_x, sign_z in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        blocked = None
        for fx, fz in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
            point = (home[0] + sign_x * reach * fx, home[1] + sign_z * reach * fz)
            inside = (
                bounds[0] - margin_x <= point[0] <= bounds[2] + margin_x
                and bounds[1] - margin_z <= point[1] <= bounds[3] + margin_z
            )
            if not inside:
                blocked = "off the edge of the map"
                break
            if (fx or fz) and not clear_of_destinations(point, locations):
                blocked = "into another destination"
                break
        if blocked is None:
            return (sign_x, sign_z), None
        if blocked not in reasons:
            reasons.append(blocked)
    return None, " or ".join(reasons)


def plan_run(home, locations):
    """Pick the probe hop and the quadrant, or say why the spot will not do."""
    bounds = map_bounds(locations, home)
    span = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    if span < MIN_HOP_WORLD * 4:
        return None, "this map is too small to hop around safely"
    reach = span / 4.0
    quadrant = None
    reason = "there is nowhere to hop to"
    while reach >= MIN_HOP_WORLD:
        quadrant, reason = choose_quadrant(home, locations, reach)
        if quadrant is not None:
            break
        reach *= 0.7
    if quadrant is None:
        return None, (
            "there is no clear space around you, even for the shortest hops. "
            f"Every direction runs {reason}. Teleport somewhere else and try "
            "again"
        )
    # Large enough that the arrow's movement stands clear of the clouds' own
    # drift, small enough that the arrow stays inside MATCH_RADIUS at any
    # scale this game has been measured at.
    probe = max(MIN_HOP_WORLD, min(reach * 0.5, span / 8.0))
    return (quadrant, probe, reach), None


def square_side(probe: float, measured: float, reach: float) -> float:
    """Size the square from how far the probe hop actually moved the arrow."""
    if measured < MIN_USEFUL_SCREEN_DELTA:
        # The probe barely registered.  Reach further rather than trusting a
        # ratio computed from noise.
        return min(reach, probe * 4.0)
    side = probe * (TARGET_SCREEN_DELTA / measured)
    return max(MIN_HOP_WORLD, min(side, reach))


def waypoints(quadrant, probe: float, side: float):
    """Offsets from home, in order: probe out, home, then a closed square.

    The run ends on ``(0, 0)`` by construction, so finishing normally *is* the
    trip home; nothing extra has to be trusted to put the player back.
    """
    sign_x, sign_z = quadrant
    return (
        (sign_x * probe, 0.0),
        (0.0, 0.0),
        (sign_x * side, 0.0),
        (sign_x * side, sign_z * side),
        (0.0, sign_z * side),
        (0.0, 0.0),
    )


def _largest_movement(before, after) -> float:
    """The biggest displacement any matched track made between two pictures.

    Matching rather than comparing the raw lists is what makes this usable as a
    stillness test: white blobs at the detection threshold flicker in and out
    between frames, and a plain length or nearest-neighbour comparison reports
    that as motion for ever.
    """
    empty = (0.0, 0.0)
    tracks = match_tracks([Sample(empty, tuple(before)), Sample(empty, tuple(after))])
    return max(
        (
            math.hypot(
                positions[1][0] - positions[0][0],
                positions[1][1] - positions[0][1],
            )
            for positions in tracks
        ),
        default=0.0,
    )


class MapCalibration:
    """The spoken, paused, six-hop calibration run for one world map."""

    def __init__(self, speaker):
        self.speaker = speaker
        self._reset()

    def _reset(self) -> None:
        self.active = False
        self.fingerprint = None
        self.home = None
        self.home_y = 0.0
        self.quadrant = None
        self.probe = 0.0
        self.reach = 0.0
        self.side = None
        self.plan = []
        self.index = 0
        self.phase = ARM
        self.samples = []
        self.pending_world = None
        self.pending_blobs = None
        self.settled = 0
        # None means "this phase's instruction has not been spoken yet", which
        # is due immediately.  A timestamp of zero looked the same and was not:
        # it made every instruction wait a full reminder interval, so the
        # player was told what to do nine seconds after they needed to know.
        self.last_spoken = None
        self.started_phase = 0.0
        self.going_home = False
        self.result = None
        self.last_sequence = None
        self.note = ""
        self._now = 0.0

    # -- starting and stopping -------------------------------------------
    def start(self, surface, player, now: float) -> bool:
        """Begin a run, or say plainly why this map or this spot will not do."""
        if surface.is_local or surface.is_vision_only:
            self.speaker.say(
                "Calibration needs the world map with your position readable. "
                "Nothing was started."
            )
            return False
        if player is None:
            self.speaker.say(
                "Your position is not readable just now, so calibration "
                "cannot start."
            )
            return False
        home = (player[0], player[2])
        plan, problem = plan_run(home, surface.locations)
        if plan is None:
            self.speaker.say(f"Calibration cannot start here: {problem}.")
            return False
        self._reset()
        self.active = True
        self.fingerprint = surface.fingerprint
        self.home = home
        self.home_y = player[1]
        self.quadrant, self.probe, self.reach = plan
        # A provisional square, replaced once the probe has measured the scale.
        self.plan = list(waypoints(self.quadrant, self.probe, self.probe * 3.0))
        self.index = 0
        self.phase = ARM
        self.started_phase = now
        self._now = now
        # Spoken here and marked as said, so the opening is not cut off half a
        # second later by the very instruction it ends with.
        self.last_spoken = now
        self.speaker.say(
            f"Map calibration. {TOTAL_MOVES} short moves teach the guide this "
            "map's scale, and the last one puts you back exactly where you are "
            "now. I will ask you to pause and unpause PCSX2 for each move. "
            "Press C again at any time to stop. "
            f"Move 1 of {TOTAL_MOVES}. Pause PCSX2."
        )
        return True

    def cancel(self, reason: str | None = None) -> None:
        """Stop, and go home rather than leaving the player somewhere strange."""
        if not self.active or self.going_home:
            return
        said = f"Calibration stopped: {reason}." if reason else "Calibration stopped."
        if self._at_home():
            self.speaker.say(f"{said} You are where you started.")
            self._reset()
            return
        self.going_home = True
        self.phase = ARM
        self.note = ""
        self.last_spoken = self._now
        self.speaker.say(
            f"{said} Taking you back to where you started. Pause PCSX2."
        )

    def _at_home(self) -> bool:
        if not self.samples or self.home is None:
            return True
        world = self.samples[-1].world
        return math.hypot(world[0] - self.home[0], world[1] - self.home[1]) < 5.0

    # -- the run ---------------------------------------------------------
    def step(
        self, *, surface, player, blobs, size, paused, move, now, sequence
    ) -> None:
        """Advance one loop pass.  ``move`` writes a world position, or raises.

        ``sequence`` identifies the captured frame.  The loop runs faster than
        the capture refreshes, so without it two consecutive passes can read
        the same picture and call it "the screen has stopped moving" -- which
        would settle a hop before the game had drawn it, pairing a new world
        position with the old arrow.
        """
        if not self.active:
            return
        self._now = now
        if surface.fingerprint != self.fingerprint:
            # There is nowhere to go home to: the coordinates the run started
            # from belong to a map that is no longer loaded.  Say where it left
            # the player rather than stopping quietly and letting them find out.
            self.speaker.say(
                "Calibration abandoned: the map changed underneath it. "
                "Nothing was learned" + self._displacement_note() + "."
            )
            self._reset()
            return
        if now - self.started_phase > MOVE_TIMEOUT_SECONDS:
            self.started_phase = now
            if self.going_home:
                self._give_up_going_home()
            else:
                self.cancel("nothing happened for three minutes")
            return

        if self.phase == ARM:
            self._arm(player, blobs, size, paused, move, now)
        elif self.phase == WRITTEN:
            self._await_unpause(paused, now)
        elif self.phase == SETTLE:
            self._settle(player, blobs, size, paused, now, sequence)

    def _away_from_home(self) -> float:
        """How far the last observed position is from where the run began."""
        world = self.pending_world
        if world is None:
            world = self.samples[-1].world if self.samples else self.home
        if world is None or self.home is None:
            return 0.0
        return math.hypot(world[0] - self.home[0], world[1] - self.home[1])

    def _displacement_note(self) -> str:
        away = self._away_from_home()
        if away < 5.0:
            return ", and you are where you started"
        return f", and you are about {away:.0f} units from where you started"

    def _give_up_going_home(self) -> None:
        """Say where the player was left, rather than stopping quietly there."""
        self.speaker.say(
            "Calibration could not put you back where you started, and left "
            f"you about {self._away_from_home():.0f} units from it. Nothing "
            "was learned. Pause PCSX2 and press T to teleport to a "
            "destination from here."
        )
        self._reset()

    def _target(self):
        if self.going_home:
            return (0.0, 0.0)
        return self.plan[self.index]

    def _say_every(self, text: str, now: float) -> None:
        """Speak an instruction now if it is new, and again only on the timer."""
        if self.last_spoken is not None and now - self.last_spoken < REMINDER_SECONDS:
            return
        self.last_spoken = now
        # A note from the hop just finished rides along with the next
        # instruction rather than being spoken separately.  Said on its own it
        # was cut off a fraction of a second later by the instruction, which
        # interrupts by design.
        self.speaker.say(f"{self.note} {text}".strip())
        self.note = ""

    def _arm(self, player, blobs, size, paused, move, now) -> None:
        """Ask for the pause, and take the before-sample while the game runs."""
        if not paused:
            # The sample has to be taken now.  PCSX2 dims a paused frame often
            # enough that the arrow falls below the white threshold, and a
            # missing arrow at exactly this moment would silently cost the hop
            # its measurement.  Kept current on the way home too, so a run that
            # cannot get back can at least say how far away it left the player.
            self._remember(player, blobs, size)
            if self.going_home:
                self._say_every("Pause PCSX2 to go back to your start.", now)
            else:
                self._say_every(
                    f"Move {self.index + 1} of {TOTAL_MOVES}. Pause PCSX2.", now
                )
            return

        if not self.going_home and self.pending_world is None:
            self._say_every(
                "Waiting for a clear view of the minimap. Unpause, keep the "
                "world map on screen for a moment, then pause again.",
                now,
            )
            return

        if not self.going_home:
            self.samples.append(Sample(self.pending_world, self.pending_blobs))
        target = self._target()
        landing = (self.home[0] + target[0], self.home[1] + target[1])
        try:
            move(landing[0], self.home_y, landing[1])
        except Exception as error:
            # The write is verified and rolled back by teleport itself, so the
            # player is still where this run last announced they were.
            self.speaker.say(
                f"Calibration stopped: the move could not be written. {error} "
                "Stay paused; I will keep trying to put you back."
            )
            # Not retried on the next pass: teleport refuses during a
            # world/local transition, and hammering it every quarter second
            # would bury the player in the same sentence.  It is retried on
            # the reminder cadence and given up on honestly at the timeout.
            self.going_home = True
            self.phase = ARM
            self.last_spoken = now
            return
        self.phase = WRITTEN
        self.started_phase = now
        self.last_spoken = now
        self.settled = 0
        self.speaker.say("Moved. Unpause PCSX2.")

    def _await_unpause(self, paused, now) -> None:
        if paused:
            self._say_every("Unpause PCSX2 to finish the move.", now)
            return
        self.phase = SETTLE
        self.started_phase = now
        self.settled = 0
        self.pending_world = None
        self.pending_blobs = None

    def _settle(self, player, blobs, size, paused, now, sequence) -> None:
        """Wait for the drawn arrow to catch up with the written position."""
        if paused:
            # Paused again before the frame was read.  Ask for the unpause
            # rather than sampling a frame that may still show the old place.
            self.phase = WRITTEN
            self.last_spoken = None
            return
        if sequence is not None and sequence == self.last_sequence:
            return
        self.last_sequence = sequence
        previous = self.pending_blobs
        if not self._remember(player, blobs, size):
            self.settled = 0
            return
        if previous is None:
            self.settled = 0
            return
        if _largest_movement(previous, self.pending_blobs) > SETTLED_SCREEN_DRIFT:
            self.settled = 0
            return
        # Two *fresh* frames that agree is the whole test, and it is enough.
        # A frame still showing the pre-hop render differs from the one after
        # it, so render lag resets the count rather than passing it.  A check
        # for "something moved since the hop" was tried instead and is worse:
        # the map's clouds drift about a pixel a frame, which over a settle is
        # the same order as a short hop, so it both accepts a stale picture
        # and would stall on a genuinely small move.
        self.settled += 1
        if self.settled >= SETTLE_SAMPLES:
            self._record(now)

    def _remember(self, player, blobs, size) -> bool:
        if player is None or blobs is None or not size or not size[0] or not size[1]:
            return False
        positions = tuple((blob.x / size[0], blob.y / size[1]) for blob in blobs)
        if not positions:
            return False
        self.pending_world = (player[0], player[2])
        self.pending_blobs = positions
        return True

    def _record(self, now) -> None:
        """One hop is finished: keep it, size the square, or finish the run."""
        if self.going_home:
            self.speaker.say("You are back where you started. Nothing was learned.")
            self._reset()
            return

        self.samples.append(Sample(self.pending_world, self.pending_blobs))
        completed = self.index + 1
        if completed == 1:
            self._size_from_probe()
        if completed >= len(self.plan):
            self._finish()
            return

        self.index = completed
        self.phase = ARM
        self.started_phase = now
        self.last_spoken = None
        self.pending_world = None
        self.pending_blobs = None
        self.note = f"Move {completed} done."

    def _size_from_probe(self) -> None:
        """Choose the square from how far the probe actually moved the arrow.

        Which track is the arrow is not decided yet -- that is what the solve
        is for -- so the largest movement any track made is used.  Clouds move
        a pixel or two, and over-estimating here only makes the square smaller.
        """
        if len(self.samples) < 2:
            return
        moved = _largest_movement(self.samples[-2].blobs, self.samples[-1].blobs)
        self.side = square_side(self.probe, moved, self.reach)
        self.plan = list(waypoints(self.quadrant, self.probe, self.side))
        if moved > MAX_SCREEN_DELTA:
            self.speaker.say(
                "That moved further on screen than expected; the remaining "
                "moves will be shorter.",
                interrupt=False,
            )

    def _finish(self) -> None:
        result, problem = solve_from_samples(self.samples)
        if result is None:
            self.speaker.say(
                f"Calibration did not settle: {problem}. Nothing was learned, "
                "and you are back where you started."
            )
            self._reset()
            return
        calibration, anchor = result
        self.result = (calibration, anchor, self.samples[-1].world)
        self.active = False

    def take_result(self):
        """Hand the finished calibration to the guide, once."""
        result = self.result
        self.result = None
        return result


def calibration_target(x: float, y: float, z: float) -> MarkerLocation:
    """A teleport target for an arbitrary spot, at the player's own altitude.

    The radius is only ever read by ``teleport._world_landing`` to decide how
    far into a sphere to drop the player.  A large one keeps the landing purely
    horizontal, which is what a calibration hop must be: a changed altitude
    would be world movement the minimap does not show.
    """
    return MarkerLocation(
        index=-1,
        x=x,
        y=y,
        z=z,
        radius=1000.0,
        name="calibration point",
    )
