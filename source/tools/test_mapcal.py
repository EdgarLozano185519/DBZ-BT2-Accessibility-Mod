"""Offline checks for the teleport-driven map calibration.

None of these need PCSX2, a save, or a player at the controls.  The run is a
state machine over spoken prompts, pause transitions and captured frames, so
all three are supplied here directly: a fake speaker records what NVDA would
have said, a fake clock advances, and the minimap is a synthetic picture drawn
through a known Jacobian.

The cases that matter most are the refusals.  A calibration that quietly
believes a cloud, or that leaves the player somewhere they did not ask to be,
is worse than one that fails and says so -- the same standard the story reader
is held to.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bt2 import mapcal
from bt2.calibration import Jacobian
from bt2.memory import Location

WIDTH, HEIGHT = 1330, 880
# A plausible map scale: about 0.00004 normalized units per world unit, north
# up, screen y growing downward.
TRUE = Jacobian(4.0e-5, 0.0, 0.0, -4.0e-5)


@dataclass
class FakeBlob:
    x: float
    y: float


class FakeSpeaker:
    def __init__(self):
        self.lines = []

    def say(self, text, interrupt=True, once=False):
        self.lines.append(text)

    def said(self, fragment):
        return any(fragment.lower() in line.lower() for line in self.lines)

    @property
    def last(self):
        return self.lines[-1] if self.lines else ""


class FakeSurface:
    is_local = False
    is_vision_only = False

    def __init__(self, locations, fingerprint="map"):
        self.locations = tuple(locations)
        self.fingerprint = fingerprint


def point(index, x, z, radius=280.0):
    return Location(index=index, address=0, x=x, y=0.0, z=z, radius=radius)


# Eight destinations spread over a few thousand units, like the recorded
# profile for the first Earth map.
LOCATIONS = (
    point(0, 303.0, -1872.0),
    point(1, 1450.0, -1221.0),
    point(2, -900.0, -400.0),
    point(3, 1200.0, 500.0),
    point(4, -1400.0, 900.0),
    point(5, 200.0, 1400.0),
    point(6, -300.0, -900.0),
    point(7, 900.0, -200.0),
)
HOME = (0.0, 0.0)


class World:
    """A minimap drawn through TRUE, plus clouds that drift on their own."""

    def __init__(self, jacobian=TRUE, clouds=2, drift=0.0006, arrow=(0.5, 0.5)):
        self.jacobian = jacobian
        self.origin = HOME
        self.arrow_home = arrow
        self.position = (HOME[0], 0.0, HOME[1])
        self.clouds = [(0.30 + 0.09 * i, 0.62) for i in range(clouds)]
        self.drift = drift
        self.frames = 0

    def move_to(self, x, y, z):
        self.position = (x, y, z)

    def blobs(self):
        self.frames += 1
        offset = self.jacobian.apply(
            self.position[0] - self.origin[0], self.position[2] - self.origin[1]
        )
        arrow = (self.arrow_home[0] + offset[0], self.arrow_home[1] + offset[1])
        drifted = [
            (cloud[0] + self.drift * self.frames, cloud[1])
            for cloud in self.clouds
        ]
        return [FakeBlob(x * WIDTH, y * HEIGHT) for x, y in [arrow] + drifted]


class Harness:
    """Drives a whole run the way the guide's loop would, and counts prompts."""

    def __init__(self, world=None, speaker=None, locations=LOCATIONS):
        self.world = world or World()
        self.speaker = speaker or FakeSpeaker()
        self.run = mapcal.MapCalibration(self.speaker)
        self.surface = FakeSurface(locations)
        self.paused = False
        self.now = 0.0
        self.sequence = 0
        self.writes = []
        self.fail_write_on = None

    def move(self, x, y, z):
        if self.fail_write_on is not None and len(self.writes) == self.fail_write_on:
            raise RuntimeError("verification failed")
        self.writes.append((x, y, z))
        self.world.move_to(x, y, z)

    def tick(self, frames=1):
        for _ in range(frames):
            self.now += 0.2
            self.sequence += 1
            self.run.step(
                surface=self.surface,
                player=self.world.position,
                blobs=self.world.blobs(),
                size=(WIDTH, HEIGHT),
                paused=self.paused,
                move=self.move,
                now=self.now,
                sequence=self.sequence,
            )

    def start(self):
        assert self.run.start(self.surface, self.world.position, self.now)

    def complete_move(self):
        """One whole hop: the player pauses, the write lands, they unpause."""
        self.tick(2)
        self.paused = True
        self.tick(2)
        self.paused = False
        self.tick(6)


def full_run(**kwargs):
    harness = Harness(**kwargs)
    harness.start()
    for _ in range(mapcal.TOTAL_MOVES):
        harness.complete_move()
    return harness


CHECKS = []


def check(function):
    CHECKS.append(function)
    return function


# --- geometry ---------------------------------------------------------------


@check
def test_waypoints_return_home():
    """The run's last waypoint is the start, so finishing is the trip back."""
    plan = mapcal.waypoints((1, 1), 200.0, 600.0)
    assert len(plan) == mapcal.TOTAL_MOVES
    assert plan[-1] == (0.0, 0.0)


@check
def test_waypoints_span_both_axes():
    """A square cannot be solved from hops along one axis alone."""
    plan = mapcal.waypoints((1, -1), 200.0, 600.0)
    assert any(offset[0] for offset in plan)
    assert any(offset[1] for offset in plan)


@check
def test_quadrant_avoids_destinations():
    """No hop may land inside a destination the player did not choose."""
    home = (0.0, 0.0)
    quadrant, reason = mapcal.choose_quadrant(home, LOCATIONS, 600.0)
    assert quadrant is not None, reason
    for offset in mapcal.waypoints(quadrant, 200.0, 600.0):
        if offset == (0.0, 0.0):
            continue  # where the player already is; see below
        landing = (home[0] + offset[0], home[1] + offset[1])
        assert mapcal.clear_of_destinations(landing, LOCATIONS)


# The recorded "Blue landmass" profile, and the position the player was
# actually standing at when the first live attempt refused: dead centre of
# point 7, at the western edge of the map, where a teleport had just put them.
BLUE_LANDMASS = (
    point(0, 303.474, -1872.49, 280.0),
    point(1, 1450.271, -1221.056, 280.0),
    point(2, 811.0, 275.0, 250.0),
    point(3, -461.0, 661.0, 210.0),
    point(4, 1645.0, -1656.0, 260.0),
    point(5, 1575.0, -356.0, 240.0),
    point(6, -1587.0, -1325.0, 300.0),
    point(7, -2045.0, -29.0, 200.0),
)
MEASURED_HOME = (-2044.7, -28.9)


@check
def test_standing_on_a_destination_can_still_calibrate():
    """The spot the player is most likely to be in is not a refusal.

    This is the first live attempt, exactly: standing on point 7, where a
    teleport had just put them, with every hop size blocked by the place they
    were standing.  Arriving is safe -- the game enters an event on the action
    button, not on arrival -- so home is exempt and only the hops are checked.
    """
    plan, problem = mapcal.plan_run(MEASURED_HOME, BLUE_LANDMASS)
    assert plan is not None, problem
    quadrant, probe, reach = plan
    for offset in mapcal.waypoints(quadrant, probe, reach):
        if offset == (0.0, 0.0):
            continue
        landing = (MEASURED_HOME[0] + offset[0], MEASURED_HOME[1] + offset[1])
        assert mapcal.clear_of_destinations(landing, BLUE_LANDMASS), landing


@check
def test_a_shorter_square_is_tried_before_giving_up():
    """A spot with no room for a big square still calibrates with a small one."""
    home = (LOCATIONS[7].x, LOCATIONS[7].z)
    assert mapcal.choose_quadrant(home, LOCATIONS, 900.0)[0] is None
    plan, problem = mapcal.plan_run(home, LOCATIONS)
    assert plan is not None, problem
    assert plan[2] < 900.0


@check
def test_quadrant_refuses_when_boxed_in():
    """Ringed by other destinations, every direction is refused, not risked."""
    crowded = tuple(
        point(index, x, z, radius=2000.0)
        for index, (x, z) in enumerate(((3000.0, 0.0), (-3000.0, 0.0),
                                        (0.0, 3000.0), (0.0, -3000.0)))
    )
    quadrant, reason = mapcal.choose_quadrant((0.0, 0.0), crowded, 600.0)
    assert quadrant is None
    assert reason


@check
def test_plan_refuses_a_crowded_spot_with_something_to_do_about_it():
    """A refusal reaches the player as a reason and a next step, not a silence."""
    crowded = tuple(
        point(index, x, z, radius=2600.0)
        for index, (x, z) in enumerate(((3000.0, 0.0), (-3000.0, 0.0),
                                        (0.0, 3000.0), (0.0, -3000.0)))
    )
    plan, problem = mapcal.plan_run((0.0, 0.0), crowded)
    assert plan is None
    assert "no clear space" in problem
    assert "another destination" in problem
    assert "Teleport somewhere else" in problem


@check
def test_square_side_follows_the_probe():
    """A probe that moved the arrow little asks for a proportionally longer hop."""
    small = mapcal.square_side(200.0, 0.011, reach=4000.0)
    large = mapcal.square_side(200.0, 0.044, reach=4000.0)
    assert small > large
    assert math.isclose(small, 400.0, rel_tol=0.01)


@check
def test_square_side_respects_the_reach():
    """It never proposes a hop that leaves the space the quadrant cleared."""
    assert mapcal.square_side(200.0, 0.0005, reach=500.0) <= 500.0
    assert mapcal.square_side(200.0, 1e-9, reach=500.0) <= 500.0


# --- the solve --------------------------------------------------------------


@check
def test_run_learns_the_true_scale():
    """A clean run recovers the Jacobian it was drawn with."""
    harness = full_run()
    result = harness.run.take_result()
    assert result is not None, harness.speaker.lines
    calibration, anchor, world = result
    assert calibration.confident
    for learned, truth in zip(
        calibration.jacobian.as_list(), TRUE.as_list()
    ):
        assert abs(learned - truth) < 2.0e-6, calibration.jacobian


@check
def test_run_reports_the_anchor_it_measured():
    """The anchor is the arrow's live screen position, which the guide needs."""
    harness = full_run()
    _calibration, anchor, world = harness.run.take_result()
    assert abs(anchor[0] - 0.5) < 0.01 and abs(anchor[1] - 0.5) < 0.01
    assert math.hypot(world[0] - HOME[0], world[1] - HOME[1]) < 1.0


@check
def test_run_ends_where_it_began():
    """The player is put back, to the coordinate, without a further prompt."""
    harness = full_run()
    assert harness.writes[-1][0] == HOME[0]
    assert harness.writes[-1][2] == HOME[1]
    assert harness.world.position[0] == HOME[0]
    assert harness.world.position[2] == HOME[1]


@check
def test_run_never_changes_altitude():
    """Every hop is horizontal; a changed altitude is movement the map hides."""
    harness = full_run()
    assert {write[1] for write in harness.writes} == {0.0}


@check
def test_clouds_do_not_win():
    """A drifting cloud fits no plausible Jacobian and is refused, not chosen."""
    harness = full_run()
    calibration, _anchor, _world = harness.run.take_result()
    # One winner only: the solve refuses ambiguity rather than picking.
    assert calibration.inlier_count >= 4


@check
def test_a_frozen_screen_times_out_and_goes_home():
    """A minimap that never redraws yields nothing, and says so rather than
    settling a hop against a picture that has not caught up."""
    frozen = World(jacobian=Jacobian(0.0, 0.0, 0.0, 0.0), drift=0.0)
    harness = Harness(world=frozen)
    harness.start()
    harness.tick(2)
    harness.paused = True
    harness.tick(2)
    harness.paused = False
    # A frozen picture is still, so the hop does record -- but nothing about
    # it can ever be solved, and the run must not claim otherwise.
    harness.tick(6)
    for _ in range(mapcal.TOTAL_MOVES):
        harness.complete_move()
    assert harness.run.take_result() is None
    assert harness.speaker.said("did not settle")


@check
def test_an_implausible_scale_is_refused():
    """A scale outside the documented band is not saved as a measurement.

    Driven straight through the solve: a map really drawn at this scale would
    put the arrow off the panel between hops, so the failure a player would
    meet is the earlier one -- but the band itself has to hold regardless of
    how the samples arrived.
    """
    absurd = Jacobian(4.0e-1, 0.0, 0.0, -4.0e-1)
    hops = ((400.0, 0.0), (0.0, 400.0), (-400.0, 0.0), (0.0, -400.0), (400.0, 400.0))
    world = (0.0, 0.0)
    screen = (0.5, 0.5)
    samples = [mapcal.Sample(world, (screen,))]
    for dx, dz in hops:
        world = (world[0] + dx, world[1] + dz)
        offset = absurd.apply(dx, dz)
        screen = (screen[0] + offset[0], screen[1] + offset[1])
        samples.append(mapcal.Sample(world, (screen,)))
    calibration = mapcal.calibration_from(mapcal.deltas_for(samples, [s.blobs[0] for s in samples]))
    assert calibration is not None
    assert not calibration.jacobian.plausible
    assert not calibration.confident


@check
def test_a_vanishing_arrow_is_refused():
    """A track absent from any sample cannot be the arrow, so the run fails."""
    samples = [
        mapcal.Sample((0.0, 0.0), ((0.5, 0.5),)),
        mapcal.Sample((500.0, 0.0), ()),
        mapcal.Sample((500.0, 500.0), ((0.52, 0.48),)),
    ]
    result, problem = mapcal.solve_from_samples(samples)
    assert result is None
    assert "not visible" in problem


# --- what the player is told ------------------------------------------------


@check
def test_every_move_is_asked_for_and_confirmed():
    """Each hop is a spoken instruction to pause, then one to unpause."""
    harness = full_run()
    pauses = sum(1 for line in harness.speaker.lines if "Pause PCSX2" in line)
    unpauses = sum(1 for line in harness.speaker.lines if "Unpause PCSX2" in line)
    assert pauses == mapcal.TOTAL_MOVES, harness.speaker.lines
    assert unpauses == mapcal.TOTAL_MOVES, harness.speaker.lines


@check
def test_the_first_prompt_says_what_will_happen():
    """Before anything moves, the player is told the shape of the whole run."""
    harness = Harness()
    harness.start()
    opening = harness.speaker.lines[0]
    assert "6 short moves" in opening
    assert "back exactly where you are now" in opening
    assert "pause and unpause" in opening
    assert "Press C again" in opening


@check
def test_moves_are_counted_aloud():
    """"Move 3 of 6" -- so a player who lost the thread can find it again."""
    harness = full_run()
    assert harness.speaker.said("Move 1 of 6")
    assert harness.speaker.said("Move 6 of 6")


@check
def test_reminders_repeat_but_do_not_nag():
    """An unanswered instruction is repeated on a timer, not every pass."""
    harness = Harness()
    harness.start()
    harness.tick(20)
    prompts = [line for line in harness.speaker.lines if "Move 1 of 6" in line]
    # 20 passes at 0.2 s is four seconds: under one reminder interval.
    assert len(prompts) == 1, prompts
    harness.tick(60)
    prompts = [line for line in harness.speaker.lines if "Move 1 of 6" in line]
    assert 2 <= len(prompts) <= 4, prompts


# --- stopping, failing, and getting home ------------------------------------


@check
def test_cancelling_goes_home():
    """C in the middle of a run takes the player back before it stops."""
    harness = Harness()
    harness.start()
    for _ in range(3):
        harness.complete_move()
    assert harness.world.position[0] != HOME[0] or harness.world.position[2] != HOME[1]
    harness.run.cancel()
    assert harness.speaker.said("Taking you back")
    harness.paused = True
    harness.tick(2)
    harness.paused = False
    harness.tick(6)
    assert harness.world.position[0] == HOME[0]
    assert harness.world.position[2] == HOME[1]
    assert not harness.run.active


@check
def test_cancelling_at_home_says_so_and_stops():
    """No pointless trip when the player is already standing on their start."""
    harness = Harness()
    harness.start()
    harness.run.cancel()
    assert harness.speaker.said("where you started")
    assert not harness.run.active


@check
def test_a_changed_map_abandons_the_run():
    """A map change underneath the run is not something to teleport through."""
    harness = Harness()
    harness.start()
    harness.complete_move()
    harness.surface = FakeSurface(LOCATIONS, fingerprint="somewhere else")
    harness.tick(1)
    assert not harness.run.active
    assert harness.speaker.said("map changed underneath")
    # There is no going home to a map that is no longer loaded, so the run
    # says where it left the player instead of stopping quietly.
    assert "units from where you started" in harness.speaker.last


@check
def test_a_refused_write_heads_home_rather_than_pressing_on():
    """Teleport's own verification failing ends the run at the start point."""
    harness = Harness()
    harness.start()
    harness.complete_move()
    harness.fail_write_on = len(harness.writes)
    harness.tick(2)
    harness.paused = True
    harness.tick(2)
    assert harness.speaker.said("could not be written")
    harness.fail_write_on = None
    harness.now += mapcal.REMINDER_SECONDS + 1.0
    harness.tick(2)
    harness.paused = False
    harness.tick(6)
    assert harness.world.position[0] == HOME[0]
    assert harness.world.position[2] == HOME[1]
    assert not harness.run.active


@check
def test_a_silent_map_is_refused_before_anything_moves():
    """No coordinate table means no teleport, and the run says so up front."""
    speaker = FakeSpeaker()
    run = mapcal.MapCalibration(speaker)
    assert not run.start(FakeSurface(()), (0.0, 0.0, 0.0), 0.0)
    assert speaker.said("needs the world map")
    assert not run.active


@check
def test_an_unreadable_position_is_refused():
    """Without a position there is nothing to hop from or measure against."""
    speaker = FakeSpeaker()
    run = mapcal.MapCalibration(speaker)
    assert not run.start(FakeSurface(LOCATIONS), None, 0.0)
    assert speaker.said("not readable")


# --- the timing hole that made this worth testing ---------------------------


@check
def test_a_repeated_frame_does_not_settle_a_hop():
    """The loop outruns the capture; the same frame twice is not two frames."""
    harness = Harness()
    harness.start()
    harness.tick(2)
    harness.paused = True
    harness.tick(2)
    harness.paused = False
    before = len(harness.run.samples)
    for _ in range(8):
        harness.now += 0.05
        harness.run.step(
            surface=harness.surface,
            player=harness.world.position,
            blobs=harness.world.blobs(),
            size=(WIDTH, HEIGHT),
            paused=False,
            move=harness.move,
            now=harness.now,
            sequence=harness.sequence,  # deliberately never advanced
        )
    assert len(harness.run.samples) == before


@check
def test_render_lag_is_waited_out():
    """One frame still showing the old minimap resets the count, not the hop.

    The lagging frame disagrees with the one after it, so stillness fails and
    the sample taken is the settled one -- which is the whole point.
    """
    harness = Harness()
    harness.start()
    harness.tick(2)
    harness.paused = True
    harness.tick(2)
    harness.paused = False
    lagged = harness.world.blobs()
    harness.world.position = (
        harness.writes[-1][0],
        harness.writes[-1][1],
        harness.writes[-1][2],
    )
    # One stale frame, then the real ones.
    harness.now += 0.2
    harness.sequence += 1
    harness.run.step(
        surface=harness.surface,
        player=harness.world.position,
        blobs=lagged,
        size=(WIDTH, HEIGHT),
        paused=False,
        move=harness.move,
        now=harness.now,
        sequence=harness.sequence,
    )
    assert len(harness.run.samples) == 1
    harness.tick(6)
    assert len(harness.run.samples) == 2
    settled = harness.run.samples[-1]
    assert abs(settled.world[0] - harness.writes[-1][0]) < 1.0


@check
def test_a_run_that_cannot_get_home_says_where_it_left_you():
    """Silence is the one unacceptable outcome of a failed return."""
    harness = Harness()
    harness.start()
    harness.complete_move()
    harness.fail_write_on = len(harness.writes)
    harness.tick(2)
    harness.paused = True
    harness.tick(2)
    assert harness.speaker.said("keep trying to put you back")
    harness.now += mapcal.MOVE_TIMEOUT_SECONDS + 1.0
    harness.tick(1)
    assert harness.speaker.said("could not put you back")
    assert "units from it" in harness.speaker.last
    assert not harness.run.active


def main() -> int:
    failures = []
    for function in CHECKS:
        try:
            function()
        except AssertionError as error:
            failures.append((function.__name__, error))
        except Exception as error:  # noqa: BLE001 - report, do not mask
            failures.append((function.__name__, f"{type(error).__name__}: {error}"))
    for name, error in failures:
        print(f"FAIL {name}: {error}")
    print(f"{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
