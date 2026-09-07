"""The resident navigation guide.

Design notes that matter for reliability:

* A world map is present when its minimap is present. Coordinate-table
  discovery may enrich that state, but cannot open, close, select, or steer a
  world-map route.
* Directional audio is the live marker pixel position minus the live player
  arrow pixel position. It therefore needs no map identity or stored atlas.
* The movement calibration is learned in parallel and is used only to convert
  that visual vector for an optional paused teleport.
* Local walkable areas have no minimap and retain their separate transform-based
  navigation path.
"""

from __future__ import annotations

import math
import os
import sys
import time
from dataclasses import dataclass, field

from .audio import arrival_tone, calibrated_tone, tone
from .calibration import (
    MIN_INLIER_DELTAS,
    AltitudeTracker,
    ArrowIdentifier,
    Calibrator,
)
from .discovery import (
    discover_surface,
    refresh_surface,
    scan_local_entities,
    validate_game,
)
from .hotkeys import (
    DestinationHotkeys,
    DirectionHotkey,
    TeleportHotkeys,
    desktop_input_allowed,
    shared_watcher,
)
from .memory import (
    LOCAL_ENTITY_RADIUS,
    Location,
    MapNotReady,
    ObjectiveNotReady,
    distance_to,
    horizontal_reach,
    player_frame,
    within_trigger,
)
from .anchor import ArrowSolver
from .atlas import MapLabeler
from .markers import DEFAULT_MARKER_RADIUS, MarkerLocation, MinimapInventory
from .navigation import (
    UNIT_NAME,
    cardinal,
    cue_for,
    kind_from_profile,
    relative_angle,
    turn_phrase,
)
from .objective import CONFIRMED, UNCONFIRMED, Objective, resolve_selector
from .profiles import MapProfile, ProfileStore, default_store
from .scan import TableScanner
from .speech import Speaker
from .surface import Surface, vision_world_surface
from .teleport import teleport
from .vision import (
    BlobTracker,
    analyze_frame,
    direct_player_arrow,
    is_map_marker,
    capture_game_window,
    find_map_markers,
    find_white_blobs,
    map_panel_region,
)

SURFACE_READY_CONFIRMATIONS = 3
SURFACE_MISSING_CONFIRMATIONS = 3
OBJECTIVE_RECHECK_SECONDS = 5.0
# A red marker must remain matched across several HUD captures before it can
# replace the current route.  The captures are separate frames, not repeated
# reads of a cached bitmap.
OBJECTIVE_CONFIRMATION_FRAMES = 3
# A verified marker may disappear briefly when the player arrow covers it.
# After this bounded grace period it is no longer evidence for the current
# route and must be reacquired.  This is especially important after fights on
# the same world map, whose geometry fingerprint does not change.
OBJECTIVE_OCCLUSION_GRACE_SECONDS = 1.5
OBJECTIVE_LOST_NOTICE_SECONDS = 4.0
# Both geometric overlap and the event banner must persist across separate
# frames before the guide tells a blind player to press Cross.
EVENT_CONFIRMATION_FRAMES = 2
CALIBRATION_SAMPLE_INTERVAL = 0.45
# Screen capture is the most expensive thing in the loop, so it is throttled
# and the single frame is shared by HUD verification, arrow calibration, and
# objective matching rather than grabbed three times.
CAPTURE_INTERVAL = 0.4
# How close counts as standing on the coordinate.  The coordinate table's own
# radius is a detection circle (200-300 units on Earth), far too coarse to stop
# guiding at, so the final approach is judged against this instead.
FINAL_APPROACH_UNITS = 10.0
# Spoken countdown while closing the last stretch.
CLOSING_CALLOUTS = (200, 150, 100, 60, 30, 20, 15)
# How often to say how calibration is going while it is unsolved.
PROGRESS_REPORT_SECONDS = 12.0
# How often a walking area may be re-scanned for figures.  The scan reads a
# few hundred kilobytes, so it is not per-tick, but it must repeat: scanning
# during a load finds nothing and would otherwise be cached forever.
LOCAL_RESCAN_SECONDS = 4.0
# Mirrors of the arrow solver's gates, for the spoken progress report.
ARROW_MIN_SAMPLES = 12
ARROW_MIN_TRAVEL = 900.0
ARROW_MIN_SPAN = 400.0
# Figures further than this from the player are not part of the scene.
LOCAL_SCENE_RADIUS = 4000.0


# How long a destination key is held before the guide gives up on serving it
# and explains why. Long enough to ride out a pass or two that could not act,
# short enough that the player is never left wondering.
PENDING_ACTION_PATIENCE = 1.5


@dataclass
class GuideState:
    surface: Surface | None = None
    objective: Objective | None = None
    active_identity: tuple | None = None
    ready_identity: tuple | None = None
    ready_count: int = 0
    missing_count: int = 0
    arrived: bool = False
    last_objective_check: float = 0.0
    last_calibration_sample: float = 0.0
    announced_inside: bool = False
    last_callout: float | None = None
    announced_degraded: bool = False
    # True once the player has picked a destination with N or B. Distinct from
    # selected_index, which the guide sets for itself when it needs somewhere
    # to start from: only this means "the player chose this".
    destination_chosen: bool = False
    # A destination key that has been read but not yet acted on. Held across
    # passes: the pass that catches the press is often one that gives up early
    # -- no table yet, scene not ready -- and dropping it there is why N and B
    # appeared dead while the key was plainly arriving.
    pending_action: str | None = None
    pending_action_since: float = 0.0
    # The destination itself, and the words it was announced with. Held rather
    # than looked up again: the list of markers is rebuilt from the minimap
    # every frame, and re-deriving a choice from it meant a marker that dropped
    # out for one frame silently moved the selection to the first entry -- so a
    # teleport could go somewhere the player never picked.
    chosen_location: object | None = None
    chosen_name: str | None = None
    pending_world_teleport: bool = False
    pending_pause_notice: bool = False
    blocked_identity: tuple | None = None
    calibrators: dict[str, Calibrator] = field(default_factory=dict)
    identifiers: dict[str, ArrowIdentifier] = field(default_factory=dict)
    trackers: dict[str, BlobTracker] = field(default_factory=dict)
    local_entities: dict[str, tuple] = field(default_factory=dict)
    altitudes: dict[str, AltitudeTracker] = field(default_factory=dict)
    announced_altitude: bool = False
    last_progress_report: float = 0.0
    capture_size: tuple[int, int] | None = None
    selected_index: int | None = None
    visit_point: int | None = None
    visit_left_world: bool = False
    inside_point: int | None = None
    awaiting_classification: int | None = None
    announced_selection: bool = False
    census_summary: str | None = None
    inventory: MinimapInventory = field(default_factory=MinimapInventory)
    last_announced_objective: Objective | None = None
    objective_unavailable_since: float | None = None
    available: tuple = ()
    last_arrow: tuple[float, float] | None = None
    last_arrow_world: tuple[float, float] | None = None
    previous_white: list = field(default_factory=list)
    pending_objective_index: int | None = None
    pending_objective_count: int = 0
    pending_objective_key: tuple | None = None
    pending_objective: Objective | None = None
    pending_objective_frame_sequence: int = -1
    objective_last_seen: float = 0.0
    announced_event_wait: bool = False
    event_confirmation_count: int = 0
    last_event_frame_sequence: int = -1
    world_map_visible: bool = False
    visual_missing_count: int = 0
    visual_ready_count: int = 0
    memory_ready: bool = False

    def reset_surface(self) -> None:
        self.surface = None
        self.objective = None
        # A destination chosen on the previous map means nothing on this one.
        self.destination_chosen = False
        self.chosen_location = None
        self.chosen_name = None
        self.active_identity = None
        self.ready_identity = None
        self.ready_count = 0
        self.arrived = False
        self.last_objective_check = 0.0
        self.last_arrow = None
        self.last_arrow_world = None
        self.previous_white = []
        self.announced_inside = False
        self.last_callout = None
        self.announced_altitude = False
        self.announced_degraded = False
        self.selected_index = None
        self.announced_selection = False
        self.census_summary = None
        self.inventory = MinimapInventory()
        self.last_announced_objective = None
        self.objective_unavailable_since = None
        self.available = ()
        self.visit_point = None
        self.visit_left_world = False
        self.inside_point = None
        self.pending_objective_index = None
        self.pending_objective_count = 0
        self.pending_objective_key = None
        self.pending_objective = None
        self.pending_objective_frame_sequence = -1
        self.objective_last_seen = 0.0
        self.announced_event_wait = False
        self.event_confirmation_count = 0
        self.last_event_frame_sequence = -1
        self.world_map_visible = False
        self.visual_missing_count = 0
        self.visual_ready_count = 0
        self.memory_ready = False
        self.blocked_identity = None


def _safe_capture():
    try:
        return capture_game_window()
    except ObjectiveNotReady:
        return None


class Guide:
    def __init__(
        self,
        pine,
        selector: str = "objective",
        store: ProfileStore | None = None,
        speaker: Speaker | None = None,
    ):
        self.pine = pine
        self.selector = selector
        self.store = store or default_store()
        self.store.load()
        self._map_labeler = MapLabeler(self.store)
        self.speaker = speaker or Speaker()
        self.scanner = TableScanner()
        self.state = GuideState()
        self._frame = None
        self._frame_time = 0.0
        self._analysis_image = None
        self._analysis = None
        self._frame_sequence = 0
        self._visual_sequence = -1
        self._scene_sequence = -1
        self._scene_ready_count = 0
        self._scene_missing_count = 0
        self._feedback_suspended = True
        # Arrow samples are screen measurements tied to one map and one window
        # size, so the solver is discarded whenever either changes.
        self._arrow_solver = ArrowSolver()
        self._arrow_key = None

    def note_capture_size(self, image) -> bool:
        """Notice a window resize.  Returns True when the size changed.

        Screen positions are recorded relative to the window, and the game view
        is pillarboxed inside it, so a resize moves every measurement: a live
        maximize from 1331x880 to 1938x1098 shifted normalized marker positions
        by up to 0.038.  Everything learned from pixels has to be discarded, or
        the guide silently navigates with a projection that no longer fits.
        """
        if image is None:
            return False
        size = (image.width, image.height)
        if self.state.capture_size == size:
            return False
        changed = self.state.capture_size is not None
        self.state.capture_size = size
        if changed:
            self.state.identifiers.clear()
            self.state.trackers.clear()
            self.state.calibrators.clear()
            self.state.last_arrow = None
            self.state.last_arrow_world = None
            self.state.objective = None
            self.state.pending_objective_key = None
            self.state.pending_objective_count = 0
            self.state.pending_objective_frame_sequence = -1
            self.state.objective_last_seen = 0.0
            self.state.available = ()
            self.state.inventory = MinimapInventory()
            self._analysis_image = None
            self._analysis = None
            self.speaker.say(
                "The PCSX2 window changed size, so the map scale is being "
                "relearned. Fly for a moment."
            )
        return changed

    def frame(self):
        """The current HUD frame, refreshed at most every CAPTURE_INTERVAL.

        An unavailable capture suspends navigation until the Dragon Adventure
        HUD is visible again; resident RAM cannot prove that a fight ended.
        """
        now = time.monotonic()
        if self._frame_time == 0.0 or now - self._frame_time >= CAPTURE_INTERVAL:
            self._frame = _safe_capture()
            self._frame_time = now
            self._frame_sequence += 1
            self._analysis_image = None
            self._analysis = None
        return self._frame

    def analyze(self, image=None):
        """Return the single shared analysis for the current captured frame."""
        image = self.frame() if image is None else image
        if image is None:
            return None
        if image is not self._analysis_image:
            self._analysis_image = image
            self._analysis = analyze_frame(image)
        return self._analysis

    def tracked_destination(self, observed, player):
        """What G reports on: the chosen destination, else the story objective.

        N and B pick among the markers the map is offering; once the player has
        picked, that is what they mean by "the destination", so it wins. With
        no explicit pick, the thing the guide is steering to is the answer.
        """
        state = self.state
        if state.destination_chosen and state.chosen_location is not None:
            return state.chosen_location
        objective = state.objective
        if objective is not None:
            if objective.location is not None:
                return objective.location
            if objective.screen_target is not None and not observed.is_local:
                try:
                    # The minimap marker converted into world coordinates, so
                    # the distance is in the same units as everything else.
                    projected = self._screen_location(observed, player, objective)
                except Exception:
                    projected = None
                if projected is not None:
                    return projected
                # Projecting needs the minimap-to-world scale, which is not
                # learned until the player has flown a little. Falling back to
                # the destination list answers the question anyway, rather than
                # claiming there is nothing to report when there are six.
        return self.selected_location(observed, player)

    def announce_direction(self, observed, player) -> None:
        """Say how far the destination is and which way to turn for it.

        Answered the moment the key is pressed. It used to be deferred to the
        guidance loop, which discards the press whenever no story objective has
        resolved -- so the key worked only sometimes, which is worse than not
        working at all. Nothing here needs the objective to be ready.

        Distance is always given, because that is what was asked for. The turn
        needs the player's own axes; when those cannot be read the compass
        bearing is given instead, and said to be a compass bearing, rather than
        dressing a direction up as a turn.
        """
        if player is None:
            self.speaker.say("Position not readable, so I cannot measure a "
                             "distance.")
            return
        try:
            target = self.tracked_destination(observed, player)
        except Exception:
            # Answering a key press must never be able to stop guidance.
            target = None
        if target is None:
            self.speaker.say("No destination selected yet.")
            return

        distance = distance_to(player, target)
        label = getattr(target, "label", None) or "Destination"
        delta_x = target.x - player[0]
        delta_z = target.z - player[2]

        frame = None
        try:
            frame = player_frame(self.pine, observed.player_address, player)
        except Exception:
            frame = None
        angle = relative_angle(delta_x, delta_z, frame[1]) if frame else None
        if angle is None:
            heading = cardinal(delta_x, delta_z)[1]
            self.speaker.say(
                f"{label}, {distance:.0f} {UNIT_NAME} {heading}. "
                "Cannot tell which way you are facing."
            )
            return
        self.speaker.say(
            f"{label}, {turn_phrase(angle)}, {distance:.0f} {UNIT_NAME}."
        )

    def navigation_scene_ready(self, analysis) -> bool:
        """Suspend immediately outside Adventure; reacquire after three frames.

        This gate runs before memory discovery, census, objective resolution,
        hotkeys and audio. During a fight only the cheap HUD-presence check
        runs. Memory left allocated by the world map cannot reopen guidance.
        """
        if self._scene_sequence != self._frame_sequence:
            self._scene_sequence = self._frame_sequence
            if analysis is not None and analysis.dragon_adventure_hud:
                self._scene_missing_count = 0
                self._scene_ready_count = min(
                    SURFACE_READY_CONFIRMATIONS, self._scene_ready_count + 1
                )
            else:
                self._scene_ready_count = 0
                self._scene_missing_count += 1
                if not self._feedback_suspended:
                    silence = getattr(self.speaker, "silence", None)
                    if silence is not None:
                        silence()
                    if sys.platform == "win32":
                        import winsound
                        winsound.PlaySound(None, 0)
                    self._feedback_suspended = True
                if self._scene_missing_count == SURFACE_MISSING_CONFIRMATIONS:
                    self.state.reset_surface()
                    self._map_labeler.reset()
        ready = self._scene_ready_count >= SURFACE_READY_CONFIRMATIONS
        if ready:
            self._feedback_suspended = False
        return ready

    def reset_world_tracking(self) -> None:
        """Discard the previous visit's visual observations on map changes."""
        state = self.state
        state.inventory = MinimapInventory()
        state.census_summary = None
        state.last_announced_objective = None
        state.objective_unavailable_since = None
        state.announced_degraded = False
        state.last_arrow = None
        state.last_arrow_world = None

    def update_objective(self, resolved: Objective, *, now=None) -> None:
        """Update guidance every frame, but speak only meaningful route changes."""
        state = self.state
        now = time.monotonic() if now is None else now
        if not resolved.same_target(state.objective):
            state.arrived = False
            state.announced_event_wait = False
            state.event_confirmation_count = 0
            state.last_event_frame_sequence = -1
        state.objective = resolved
        if resolved.confirmed:
            state.objective_unavailable_since = None
            state.announced_degraded = False
            if not resolved.same_target(state.last_announced_objective):
                self.speaker.say(f"Objective: {resolved.label}.")
                state.last_announced_objective = resolved
        elif state.objective_unavailable_since is None:
            state.objective_unavailable_since = now
        elif (
            not state.announced_degraded
            and now - state.objective_unavailable_since >= OBJECTIVE_LOST_NOTICE_SECONDS
        ):
            self.speaker.say("Waiting for a clear objective marker.")
            state.announced_degraded = True

    # -- calibration -----------------------------------------------------
    def calibrator_for(self, surface: Surface) -> Calibrator:
        """The calibrator of the track currently believed to be the arrow.

        Kept as a method because profiles, announcements and persistence all
        speak in terms of one calibrator per map.  Before the arrow is
        identified this returns a placeholder that is simply not confident.
        """
        identifier = self.identifier_for(surface)
        winner = identifier.best()
        if winner is not None:
            # ArrowIdentifier owns the calibrator that actually learned from
            # the moving arrow.  Publish that exact object to the rest of the
            # guide; keeping the old placeholder here left projection_for()
            # and persist_calibration() permanently disconnected from the
            # successful solve until the next process restart.
            self.state.calibrators[surface.fingerprint] = winner.calibrator
            return winner.calibrator
        placeholder = self.state.calibrators.get(surface.fingerprint)
        if placeholder is None:
            placeholder = Calibrator(surface.fingerprint)
            profile = self.store.map_profile(
                surface.fingerprint, len(surface.locations)
            )
            if profile.usable_at(self.state.capture_size):
                # A previously learned map is calibrated the moment its arrow
                # is found -- the anchor is live, so nothing re-converges.  A
                # scale learned at another window size does not apply.
                placeholder.seed(profile.jacobian)
            self.state.calibrators[surface.fingerprint] = placeholder
        return placeholder

    def augment_local(self, surface: Surface, player) -> Surface:
        """Give a walking area the same destination list a world map has.

        Walking areas publish no coordinate table -- the only one in memory is
        the previous world map's, stale -- so the destinations come from the
        actor transform pool instead.  The scan is expensive, so its result is
        cached and the addresses are then read live, which both costs a handful
        of words per tick and follows a figure that walks around.

        The cache is retried rather than trusted forever: scanning while the
        area is still loading finds nothing, and an actor slot can be reused,
        either of which would otherwise leave the guide permanently pointing at
        nothing in that area.
        """
        if not surface.is_local:
            return surface

        cached = self.state.local_entities.get(surface.fingerprint)
        addresses = cached[0] if cached else None
        scanned_at = cached[1] if cached else 0.0
        now = time.monotonic()

        positions = ()
        if addresses:
            positions = self.pine.read_vector3_many(addresses)
            if not self._positions_plausible(positions, player):
                addresses = None

        if not addresses and now - scanned_at >= LOCAL_RESCAN_SECONDS:
            try:
                entities = scan_local_entities(self.pine, player)
            except (MapNotReady, OSError, ValueError):
                entities = ()
            addresses = tuple(entity.address for entity in entities)
            self.state.local_entities[surface.fingerprint] = (addresses, now)
            positions = (
                self.pine.read_vector3_many(addresses) if addresses else ()
            )

        if not addresses or not positions:
            return surface

        locations = tuple(
            Location(
                index,
                address,
                position[0],
                position[1],
                position[2],
                LOCAL_ENTITY_RADIUS,
                f"nearby character {index + 1}",
                True,
            )
            for index, (address, position) in enumerate(zip(addresses, positions))
        )
        return Surface(
            kind=surface.kind,
            table_address=surface.table_address,
            player_address=surface.player_address,
            locations=locations,
            fingerprint=surface.fingerprint,
            name=surface.name,
            named=surface.named,
            stage_signature=surface.stage_signature,
            mirrors=surface.mirrors,
            local_right=surface.local_right,
            local_forward=surface.local_forward,
            descriptor=surface.descriptor,
        )

    @staticmethod
    def _positions_plausible(positions, player) -> bool:
        """Whether cached entity slots still hold a figure in this scene."""
        if not positions:
            return False
        for position in positions:
            if not all(math.isfinite(value) for value in position):
                return False
            if max(abs(value) for value in position) >= 100_000.0:
                return False
            # An actor slot reused by something far outside the scene is no
            # longer the figure that was found.
            if math.dist(position, player) > LOCAL_SCENE_RADIUS:
                return False
        return True

    def altitude_for(self, surface: Surface) -> AltitudeTracker:
        """The learned flight altitude for this map, created on first sight."""
        tracker = self.state.altitudes.get(surface.fingerprint)
        if tracker is None:
            tracker = AltitudeTracker()
            profile = self.store.map_profile(
                surface.fingerprint, len(surface.locations)
            )
            if profile.flight_altitude is not None:
                tracker.seed(profile.flight_altitude)
            self.state.altitudes[surface.fingerprint] = tracker
        return tracker

    def identifier_for(self, surface: Surface) -> ArrowIdentifier:
        identifier = self.state.identifiers.get(surface.fingerprint)
        if identifier is None:
            identifier = ArrowIdentifier(surface.fingerprint)
            self.state.identifiers[surface.fingerprint] = identifier
        return identifier

    def tracker_for(self, surface: Surface) -> BlobTracker:
        tracker = self.state.trackers.get(surface.fingerprint)
        if tracker is None:
            tracker = BlobTracker()
            self.state.trackers[surface.fingerprint] = tracker
        return tracker

    def locate_arrow(self, surface: Surface, player, image, analysis=None):
        """Find the player arrow.

        Once the arrow's track is known, follow it cheaply by prediction.  Until
        then every white element is a candidate and the answer comes from
        behaviour, not appearance -- the map's clouds are white, drift on their
        own, and one of them measured larger than the arrow.
        """
        if image is None or surface.is_local:
            return None
        analysis = analysis or self.analyze(image)
        if analysis is None:
            return None
        direct = direct_player_arrow(analysis.white_blobs)
        if direct is not None:
            return direct
        if player is None:
            return None
        calibrator = self.calibrator_for(surface)
        calibration = calibrator.calibration
        if calibration is not None and calibration.confident:
            anchor = self.state.last_arrow
            last_player = self.state.last_arrow_world
            predicted = None
            if anchor is not None and last_player is not None:
                offset = calibration.jacobian.apply(
                    player[0] - last_player[0], player[2] - last_player[1]
                )
                predicted = (anchor[0] + offset[0], anchor[1] + offset[1])
            if predicted is not None:
                radius = 0.08 * max(image.width, image.height)
                center_x = predicted[0] * image.width
                center_y = predicted[1] * image.height
                candidates = [
                    blob
                    for blob in analysis.white_blobs
                    if math.hypot(blob.x - center_x, blob.y - center_y) <= radius
                ]
                if candidates:
                    return min(
                        candidates,
                        key=lambda blob: math.hypot(
                            blob.x - center_x, blob.y - center_y
                        ),
                    )

        # Restrict the search to the minimap.  Across the whole window a live
        # capture offered 46 white candidates, most of them PCSX2's own title
        # bar, menu and status text; the panel holds about six.
        blobs = list(analysis.white_blobs)
        seen = self.tracker_for(surface).update(blobs)
        positions = {
            key: (blob.x / image.width, blob.y / image.height)
            for key, blob in seen.items()
        }
        self.identifier_for(surface).observe((player[0], player[2]), positions)
        winner = self.identifier_for(surface).best()
        if winner is None:
            return None
        return seen.get(winner.identifier)

    def observe_arrow(
        self, surface: Surface, player: tuple[float, float, float] | None, image,
        analysis=None,
    ) -> bool:
        """Advance arrow identification and calibration for one frame.

        The arrow is drawn on every world map regardless of progress, which is
        why calibration never depends on unlocked content.
        """
        if image is None or surface.is_local:
            return False
        now = time.monotonic()
        if now - self.state.last_calibration_sample < CALIBRATION_SAMPLE_INTERVAL:
            return False
        self.state.last_calibration_sample = now

        arrow = self.locate_arrow(surface, player, image, analysis)
        if arrow is None:
            return False
        anchor = (arrow.x / image.width, arrow.y / image.height)
        # The direct appearance path needs no behavioural identification, but
        # its successive player/arrow pairs still teach the same calibration
        # later used by optional teleport conversion.
        if player is not None and not surface.is_vision_only:
            self.calibrator_for(surface).observe(
                player[0], player[2], anchor[0], anchor[1]
            )
        self.state.last_arrow = anchor
        self.state.last_arrow_world = (
            (player[0], player[2]) if player is not None else None
        )
        return True

    def selected_location(self, surface: Surface, player):
        """A local or explicitly requested coordinate-table destination.

        The normal story-objective path never calls this for a world map; it
        follows the minimap vector and refuses to manufacture a table fallback.
        """
        if not surface.locations:
            return None
        available = self.state.available
        if available and not surface.is_local:
            # Markers decide what exists; the table only says where it is.
            if self.state.selected_index is None:
                self.state.selected_index = available[0].location.index
            for entry in available:
                if entry.location.index == self.state.selected_index:
                    return entry.location
            self.state.selected_index = available[0].location.index
            return available[0].location
        if self.state.selected_index is None:
            # Default to the nearest destination the player has not already
            # found to be a free event.  Those are recorded from gameplay, so
            # each one the player rules out sharpens this guess.
            profile = self.store.map_profile(
                surface.fingerprint, len(surface.locations)
            )
            candidates = [
                item
                for item in surface.locations
                if surface.is_local or profile.worth_guiding_to(item.index)
            ] or list(surface.locations)
            nearest = min(candidates, key=lambda item: distance_to(player, item))
            self.state.selected_index = nearest.index
        index = self.state.selected_index % len(surface.locations)
        return surface.locations[index]

    def track_visit(self, surface: Surface, player) -> None:
        """Notice that the player went into a destination and came back.

        The mod can see the boundaries of a visit from RAM alone -- inside a
        destination's radius, the world surface goes away, the world surface
        returns.  What it cannot see is whether the story moved on, so when it
        has no record for that destination it asks, once.
        """
        state = self.state
        if surface.is_local:
            if state.visit_point is not None:
                state.visit_left_world = True
            return
        if not surface.locations:
            return

        if state.visit_point is not None and state.visit_left_world:
            index = state.visit_point
            state.visit_point = None
            state.visit_left_world = False
            profile = self.store.map_profile(
                surface.fingerprint, len(surface.locations)
            )
            if profile.kind_of(index) is None:
                state.awaiting_classification = index
                label = profile.point_names.get(index) or f"map point {index + 1}"
                self.speaker.say(
f"Back from {label}. S story, F free, U nothing?"
                )
            return

        inside = None
        for location in surface.locations:
            if within_trigger(player, location):
                inside = location.index
                break
        if inside is not None and inside != state.inside_point:
            state.visit_point = inside
            state.visit_left_world = False
        state.inside_point = inside

    def classify_visit(self, surface: Surface, kind: str, player=None) -> bool:
        """Record what a destination turned out to be.

        Normally this answers the question ``track_visit`` asked after a round
        trip.  It also works with nothing pending, so a player standing on a
        point where Cross does nothing can mark it straight away -- that case
        never produces a round trip, because they never leave the world map.
        """
        if surface.is_local:
            return False
        index = self.state.awaiting_classification
        if index is None and player is not None and not surface.is_local:
            nearest = min(
                surface.locations,
                key=lambda item: distance_to(player, item),
                default=None,
            )
            if nearest is not None and within_trigger(player, nearest):
                index = nearest.index
        if index is None:
            return False
        self.state.awaiting_classification = None
        profile = self.store.map_profile(
            surface.fingerprint, len(surface.locations)
        )
        profile.point_kinds[index] = kind
        try:
            self.store.save_map(profile)
        except OSError as error:
            self.speaker.say(f"Could not save that: {error}")
            return True
        label = profile.point_names.get(index) or f"map point {index + 1}"
        remaining = sum(
            1
            for i in range(len(surface.locations))
            if profile.worth_guiding_to(i)
        )
        word = "nothing" if kind == profile.KIND_NONE else f"{kind} event"
        self.speaker.say(f"{label}: {word}. {remaining} left.")
        # A destination just ruled out should not stay selected.
        if self.state.selected_index == index and not profile.worth_guiding_to(index):
            self.state.selected_index = None
            self.state.announced_selection = False
        return True

    def cycle_destination(self, surface: Surface, player, action: str) -> None:
        """Step through what the map is offering, story destination first."""
        available = self.state.available
        if available and not surface.is_local:
            order = [entry.location.index for entry in available]
            current = self.selected_location(surface, player)
            position = (
                order.index(current.index) if current.index in order else 0
            )
            if action == "next":
                position = (position + 1) % len(order)
            elif action == "previous":
                position = (position - 1) % len(order)
            self.state.selected_index = order[position]
            self.state.destination_chosen = True
            entry = available[position]
            profile = self.store.map_profile(
                surface.fingerprint, len(surface.locations)
            )
            name = (
                profile.point_names.get(entry.location.index)
                or entry.location.label
            )
            # Remember the decision, and the words it was given in, so that
            # teleporting cannot land somewhere else or call it something else.
            self.state.chosen_location = entry.location
            self.state.chosen_name = name
            cue = cue_for(player, entry.location, name, entry.kind)
            self._reset_approach()
            self.speaker.say(
                f"{cue.instruction} "
                f"{'Story' if entry.is_story else 'Free'} event, "
                f"{position + 1} of {len(order)}."
            )
            return

        if not surface.locations:
            self.speaker.say(
                "No destinations found on this map yet. Keep the world map in "
                "view for a moment while they are located."
            )
            return
        current = self.selected_location(surface, player)
        if action == "next":
            self.state.selected_index = (current.index + 1) % len(surface.locations)
        elif action == "previous":
            self.state.selected_index = (current.index - 1) % len(surface.locations)
        chosen = self.selected_location(surface, player)
        profile = (MapProfile(surface.fingerprint) if surface.is_local else
                   self.store.map_profile(surface.fingerprint,len(surface.locations)))
        name = profile.point_names.get(chosen.index) or chosen.label
        self.state.destination_chosen = True
        self.state.chosen_location = chosen
        self.state.chosen_name = name
        node_type = kind_from_profile(profile, chosen.index, surface.is_local)
        cue = cue_for(player, chosen, name, node_type)
        self._reset_approach()
        recorded = None if surface.is_local else profile.kind_of(chosen.index)
        suffix = ""
        if recorded == profile.KIND_FREE:
            suffix = " Free event."
        elif recorded == profile.KIND_STORY:
            suffix = " Story event."
        elif recorded == profile.KIND_NONE:
            suffix = " Nothing here."
        self.speaker.say(
            f"{cue.instruction} Destination {chosen.index + 1} of "
            f"{len(surface.locations)}.{suffix}"
        )

    def _reset_approach(self) -> None:
        self.state.announced_selection = True
        self.state.arrived = False
        self.state.announced_inside = False
        self.state.last_callout = None

    def _rediscover(self, player):
        """Re-read the surface the way the loop sees it, for teleport's check.

        It must include the local entity list.  Without it, teleport
        revalidated a walking area against the single authored interaction
        while the chosen destination's index came from the entity list, so it
        either moved the player to the wrong figure or refused outright.
        """

        def again():
            surface = self.name_surface(
                discover_surface(self.pine, self.scanner)
            )
            return self.augment_local(surface, player)

        return again

    def _screen_bearing(self, surface: Surface, player, objective):
        """World direction that moves the player toward an on-screen marker."""
        if objective.screen_target is None:
            return None
        projection = self.projection_for(surface, player)
        if projection is None:
            return None
        anchor = self.state.last_arrow
        if anchor is None:
            return None
        return projection.world_bearing(
            objective.screen_target[0] - anchor[0],
            objective.screen_target[1] - anchor[1],
        )

    def _screen_offset(self, objective, image):
        """Pixel vector from the tracked player arrow to a minimap target."""
        if objective.screen_target is None or self.state.last_arrow is None:
            return None
        delta_x = (objective.screen_target[0] - self.state.last_arrow[0]) * image.width
        delta_y = (objective.screen_target[1] - self.state.last_arrow[1]) * image.height
        return delta_x, delta_y, math.hypot(delta_x, delta_y)

    def _screen_location(self, surface: Surface, player, objective):
        """Convert a live minimap target only when a world write needs it.

        Ordinary guidance never calls this: it follows screen pixels directly.
        Teleport must ultimately write world coordinates, so it uses the
        inverse movement calibration anchored on the live player arrow.  No
        coordinate-table point participates in the conversion.
        """
        if player is None or surface.is_vision_only:
            return None
        bearing = self._screen_bearing(surface, player, objective)
        if bearing is None:
            return None
        radii = sorted(location.radius for location in surface.locations)
        radius = radii[len(radii) // 2] if radii else DEFAULT_MARKER_RADIUS
        return MarkerLocation(
            index=-1,
            x=player[0] + bearing[0],
            y=0.0,
            z=player[2] + bearing[1],
            radius=radius,
            name=objective.label,
        )

    def projection_for(self, surface: Surface, player):
        """The live anchored projection, or None while still learning."""
        if surface.is_local or surface.is_vision_only or player is None:
            return None
        calibrator = self.calibrator_for(surface)
        if self.state.last_arrow is None:
            return None
        anchor_world = self.state.last_arrow_world
        if anchor_world is None:
            return None
        # Anchor on the arrow's own frame, then carry forward by the movement
        # since it was seen; that keeps the projection valid between captures.
        projection = calibrator.projection(anchor_world, self.state.last_arrow)
        if projection is None:
            return None
        return projection

    # -- story-objective verification -----------------------------------
    def stabilize_story_objective(
        self,
        observed: Objective,
        *,
        now: float | None = None,
        frame_sequence: int | None = None,
    ) -> Objective:
        """Require consecutive minimap observations before guiding there.

        A raw confirmed object means one frame contains exactly one red marker;
        a candidate is a structural non-red highlight. This stateful step makes
        either safe to act on: three distinct captured frames must point at the
        same screen position. Missing observations retain the previous route
        only for a bounded occlusion grace, then force reacquisition.
        """
        if self.selector.casefold() != "objective":
            return observed
        now = time.monotonic() if now is None else now
        if not observed.has_direction:
            self.state.pending_objective_index = None
            self.state.pending_objective_key = None
            self.state.pending_objective_count = 0
            self.state.pending_objective_frame_sequence = -1
            current = self.state.objective
            if current is not None and current.confirmed:
                if self.state.objective_last_seen == 0.0:
                    self.state.objective_last_seen = now
                age = now - self.state.objective_last_seen
                # The arrow can hide the marker at contact. Keep it just long
                # enough to confirm overlap plus the event banner, but never
                # indefinitely: a stale route must not survive progression.
                if age <= OBJECTIVE_OCCLUSION_GRACE_SECONDS:
                    return current
            self.state.objective_last_seen = 0.0
            return observed

        current = self.state.objective
        same_current = (
            current is not None and current.confirmed and observed.same_target(current)
        )
        if same_current:
            self.state.pending_objective_index = None
            self.state.pending_objective_key = None
            self.state.pending_objective_count = 0
            self.state.pending_objective_frame_sequence = -1
            self.state.objective_last_seen = now
            if observed.confirmed:
                return observed
            return Objective(
                observed.location,
                CONFIRMED,
                observed.method + ", stable across minimap frames",
                observed.screen_target,
            )

        key = observed.stable_key
        if self.state.pending_objective_key is not None and (
            self.state.pending_objective_key == key
            or observed.same_target(self.state.pending_objective)
        ):
            if (
                frame_sequence is None
                or self.state.pending_objective_frame_sequence != frame_sequence
            ):
                self.state.pending_objective_count += 1
                self.state.pending_objective_frame_sequence = (
                    -1 if frame_sequence is None else frame_sequence
                )
        else:
            self.state.pending_objective_key = key
            self.state.pending_objective = observed
            self.state.pending_objective_index = (
                observed.location.index if observed.location is not None else None
            )
            self.state.pending_objective_count = 1
            self.state.pending_objective_frame_sequence = (
                -1 if frame_sequence is None else frame_sequence
            )

        count = self.state.pending_objective_count
        if count < OBJECTIVE_CONFIRMATION_FRAMES:
            return Objective(
                None,
                UNCONFIRMED,
                f"{observed.label}; "
                f"confirming map scan {count}/{OBJECTIVE_CONFIRMATION_FRAMES}",
            )

        self.state.pending_objective_index = None
        self.state.pending_objective_key = None
        self.state.pending_objective_count = 0
        self.state.pending_objective_frame_sequence = -1
        self.state.objective_last_seen = now
        if observed.confirmed:
            return observed
        return Objective(
            observed.location,
            CONFIRMED,
            observed.method + ", stable across minimap frames",
            observed.screen_target,
        )

    def _screen_arrival_confirmed(
        self,
        overlap: bool,
        event_description: bool,
        *,
        frame_sequence: int | None = None,
    ) -> bool:
        """Gate the Cross prompt on two independent visual observations."""
        state = self.state
        if not overlap or not event_description:
            state.event_confirmation_count = 0
            state.last_event_frame_sequence = -1
            return False
        sequence = self._frame_sequence if frame_sequence is None else frame_sequence
        if state.last_event_frame_sequence != sequence:
            state.last_event_frame_sequence = sequence
            state.event_confirmation_count += 1
        return state.event_confirmation_count >= EVENT_CONFIRMATION_FRAMES

    def report_calibration_progress(self, surface: Surface) -> None:
        """Announce progress toward learning this map's scale, at intervals."""
        now = time.monotonic()
        if now - self.state.last_progress_report < PROGRESS_REPORT_SECONDS:
            return
        self.state.last_progress_report = now
        identifier = self.identifier_for(surface)
        winner = identifier.best()
        if winner is not None:
            deltas = len(winner.calibrator.deltas)
            self.speaker.say(
                f"Learning the map scale: {deltas} of "
                f"{MIN_INLIER_DELTAS} movements. Keep flying, and change "
                "direction at least once.",
                once=True,
            )
            return
        self.speaker.say(
            f"Looking for the map cursor: {identifier.describe()}. "
            "Fly, then hold still for a moment.",
            once=True,
        )

    def persist_calibration(self, surface: Surface) -> None:
        calibrator = self.calibrator_for(surface)
        if calibrator is None or calibrator.calibration is None:
            return
        calibration = calibrator.calibration
        if not calibration.confident:
            return
        profile = self.store.map_profile(surface.fingerprint, len(surface.locations))
        improved = (
            profile.jacobian is None
            or calibration.inlier_count > profile.jacobian_samples
        )
        if not improved:
            return
        profile.jacobian = calibration.jacobian
        profile.jacobian_samples = calibration.inlier_count
        profile.jacobian_error = calibration.median_error
        profile.jacobian_capture_size = self.state.capture_size
        tracker = self.state.altitudes.get(surface.fingerprint)
        if tracker is not None and tracker.known:
            profile.flight_altitude = tracker.resting
        try:
            self.store.save_map(profile)
        except OSError as error:
            self.speaker.say(f"Could not save the map profile: {error}", once=True)

    # -- naming ----------------------------------------------------------
    def survey_map(self, surface: Surface, image=None, analysis=None) -> None:
        """Build a stable inventory and announce it once per map visit.

        World coordinates are intentionally absent from this step.  The
        objective resolver and audio consume marker pixels directly; pairing
        the census back to a table was the source of wrong-route fallbacks.
        """
        if surface.is_local or (image is None and analysis is None):
            self.state.available = ()
            return
        analysis = analysis or self.analyze(image)
        if analysis is None or not analysis.world_map_visible:
            return
        census = self.state.inventory.observe(analysis, self._frame_sequence)
        summary = census.describe()
        if self.state.inventory.settled and summary != self.state.census_summary:
            # Announced again when it genuinely changes, not just on arrival.
            # Finishing a story event moves the markers while the map stays the
            # same, and the guide used to go on describing the set it first saw.
            # Only the description is compared, so a dot flickering under the
            # player's arrow cannot cause chatter.
            first = self.state.census_summary is None
            self.state.census_summary = summary
            self.speaker.say(
                summary if first else f"Destinations changed: {summary}",
                interrupt=False,
            )
        # Kept empty deliberately: available destinations are screen objects,
        # not table locations.  N/B remains an explicit legacy table selector
        # for diagnostics, but the objective path never consults it.
        self.state.available = ()

    def observe_markers(self, surface: Surface, image, player=None) -> None:
        """Fit this map's projection from the player arrow.

        The arrow is a known correspondence -- it *is* the player -- so the
        projection follows from flying around for a few seconds.  Matching
        markers to table entries was tried first and could not be made to work:
        four markers against six points left assignments within 1.13x of one
        another, and the accumulated positions that were supposed to break the
        tie turned out to be mostly HUD text and panel-animation duplicates.

        Once solved, ``markers.destinations`` pairs each drawn marker with the
        entry it sits on, and any table entry without a marker is dropped.
        """
        if image is None or surface.is_local or not surface.locations:
            return
        profile = self.store.map_profile(
            surface.fingerprint, len(surface.locations)
        )
        if profile.usable_map_affine_at((image.width, image.height)):
            return
        if player is None:
            return

        key = (surface.fingerprint, image.width, image.height)
        if key != self._arrow_key:
            self._arrow_key = key
            self._arrow_solver = ArrowSolver()

        markers = [b for b in find_map_markers(image) if is_map_marker(b)]
        region = map_panel_region(image, markers)
        if region is None:
            return
        # White elements on the panel: the arrow, plus any white marker.  Which
        # one is the arrow is decided by which one moves with the player.
        self._arrow_solver.observe(
            player, find_white_blobs(image, region), region
        )

        solved = self._arrow_solver.solve()
        if solved is None:
            # Report whichever gate is actually holding it up.  Saying
            # "2739 of 900 units" while the real blocker was a 201-unit
            # east-west spread told the player nothing they could act on --
            # circling covers distance without widening the map coverage the
            # fit needs.
            if self._arrow_solver.sample_count >= 4:
                span_x, span_z = self._arrow_solver.spans
                if span_x < ARROW_MIN_SPAN:
                    need = "east and west"
                    have, want = span_x, ARROW_MIN_SPAN
                elif span_z < ARROW_MIN_SPAN:
                    need = "north and south"
                    have, want = span_z, ARROW_MIN_SPAN
                elif self._arrow_solver.travel < ARROW_MIN_TRAVEL:
                    need = "further"
                    have, want = self._arrow_solver.travel, ARROW_MIN_TRAVEL
                else:
                    need = "a little more"
                    have, want = 0.0, 0.0
                message = f"Learning the map. Fly {need}"
                if want:
                    message += f": {have:.0f} of {want:.0f} units"
                self.speaker.say(message + ".", once=True)
            return

        coefficients, residual, samples = solved
        profile.map_affine = coefficients
        profile.map_affine_capture_size = (image.width, image.height)
        try:
            self.store.save_map(profile)
        except OSError:
            return
        self.speaker.say(
            f"{profile.display_name} solved from {samples} arrow samples, "
            f"{residual:.0f} pixel error."
        )

    def record_geometry(self, surface: Surface) -> None:
        """Save a world map's coordinates the first time it is encountered.

        The tables are built at runtime -- they are absent from the ELF and
        from DAdventure.pak -- so visiting a map is the only way to obtain its
        geometry.  Recording it automatically means touring the game builds a
        complete atlas without the player running anything.
        """
        if surface.is_local or not surface.locations:
            return
        profile = self.store.map_profile(
            surface.fingerprint, len(surface.locations)
        )
        if not profile.record_points(surface.locations):
            return
        try:
            self.store.save_map(profile)
        except OSError:
            return
        self.speaker.say(
            f"Recorded the layout of {profile.display_name}: "
            f"{len(surface.locations)} destinations."
        )

    def name_surface(self, surface: Surface, analysis=None) -> Surface:
        if analysis is not None and not surface.is_local:
            try:
                return self._map_labeler.observe(surface,analysis,self._frame_sequence)
            except Exception:
                # Labelling is optional. Never discard a readable minimap or
                # terminate guidance because a profile/image cannot be labelled.
                return surface
        if surface.is_vision_only:
            return surface
        if surface.is_local:
            profile = self.store.area_profile(surface.fingerprint)
        else:
            profile = self.store.map_profile(
                surface.fingerprint, len(surface.locations)
            )
        return Surface(
            kind=surface.kind,
            table_address=surface.table_address,
            player_address=surface.player_address,
            locations=surface.locations,
            fingerprint=surface.fingerprint,
            name=profile.display_name,
            named=profile.is_named,
            stage_signature=surface.stage_signature,
            mirrors=surface.mirrors,
            local_right=surface.local_right,
            local_forward=surface.local_forward,
            descriptor=surface.descriptor,
        )

    # -- announcements ---------------------------------------------------
    def announce_surface(self, surface: Surface) -> None:
        calibrator = (
            None
            if surface.is_local or surface.is_vision_only
            else self.state.calibrators.get(surface.fingerprint)
        )
        calibration = calibrator.calibration if calibrator else None
        if surface.is_local:
            self.speaker.say(f"Entered {surface.describe()}.")
            return
        if surface.is_vision_only:
            self.speaker.say(
                f"{surface.display_name}. Following the minimap."
            )
            return
        if calibration is not None and calibration.confident:
            self.speaker.say(
f"{surface.describe()}. Scale known."
            )
        else:
            self.speaker.say(
f"{surface.describe()}."
            )

    # -- main loop -------------------------------------------------------
    def run(self, stop_event=None, close_speaker: bool = True) -> None:
        if sys.platform != "win32":
            raise RuntimeError(
                "The current audio guide uses Windows' built-in wave player"
            )
        import winsound

        self.speaker.say(
"Guide active."
        )
        hotkeys = TeleportHotkeys()
        destinations = DestinationHotkeys()
        # Polled early, unlike the destination keys: see DirectionHotkey.
        direction_key = DirectionHotkey()
        # Menus are read only while navigation guidance is suspended, so the two
        # can never talk over one another.
        from .menus import MenuReader
        menus = MenuReader(self.speaker)
        # Story prose is read in the same place and for the same reason: it is
        # the one point in the loop where navigation guidance is not speaking.
        from .story import StoryReader
        story = StoryReader(self.speaker)
        if hotkeys.controller_name:
            self.speaker.say(f"Teleport: T key or L1 on {hotkeys.controller_name}.")
        else:
            self.speaker.say(
                "Teleport: T key. DualSense L1 will activate when the "
                "controller is found."
            )
        self.speaker.say(
            "T teleports. N and B change local or explicitly selected "
            "destinations. S, F or U says what a place turned out to be.",
            interrupt=False,
        )

        state = self.state
        desktop_suspended = False
        try:
            while stop_event is None or not stop_event.is_set():
                if os.environ.get("BT2_DESKTOP_UI") == "1":
                    import ctypes
                    if not desktop_input_allowed(ctypes.windll.user32):
                        if not desktop_suspended:
                            self.speaker.silence()
                            winsound.PlaySound(None,0)
                            desktop_suspended = True
                            # The player is reading with their screen reader,
                            # not playing. Re-announce when they come back.
                            menus.suspend()
                        # Forget everything queued: the player was reading,
                        # not playing, and a press from then must not fire on
                        # their return.
                        shared_watcher().drain()
                        if stop_event is not None:
                            stop_event.wait(.15)
                        else:
                            time.sleep(.15)
                        continue
                    desktop_suspended = False
                # Read once per pass and answered on every path below. It used
                # to be read on one branch only, so a press while the scene was
                # not ready simply vanished.
                wants_direction = direction_key.pressed()
                # Read here for the same reason: the destination keys used to
                # be read below the point where the loop gives up when no story
                # objective has resolved. On a fresh map, where none has, N and
                # B did nothing at all.
                polled = destinations.poll()
                if polled is not None:
                    state.pending_action = polled
                    state.pending_action_since = time.monotonic()
                pending_action = state.pending_action
                try:
                    # One frame per iteration, shared by the HUD cross-check
                    # below, arrow calibration, and objective matching.
                    captured = self.frame()
                    captured_analysis = self.analyze(captured) if captured is not None else None
                    # Ask the scene gate first so its own counters stay current,
                    # then let a menu marker overrule it. The Game Level chooser
                    # reads as gameplay to the HUD heuristic; memory says
                    # plainly that a menu is up, and that is checkable.
                    scene_ready = self.navigation_scene_ready(captured_analysis)
                    if scene_ready and menus.in_adventure_menu(self.pine):
                        scene_ready = False
                    if not scene_ready:
                        # Drain input edges while inactive: an L1 pressed in
                        # combat must never become a teleport after returning.
                        hotkeys.poll()
                        destinations.poll()
                        # Outside Adventure the player is usually in a menu, and
                        # this is the only point where nothing else is speaking.
                        menus.poll(self.pine, time.monotonic())
                        # Cutscenes land here too: they are not the world map,
                        # so the scene gate holds guidance off through them.
                        #
                        # Only where the menu reader does not know the screen.
                        # On a mapped menu the same pointer aims at that
                        # screen's subtitle, and reading it here would announce
                        # every subtitle automatically -- which is exactly what
                        # F12 was made a key press to avoid, because it slows
                        # browsing to a crawl. An unknown screen is where a
                        # cutscene lives.
                        if menus.screen is None:
                            story.poll(self.pine, time.monotonic())
                        if wants_direction:
                            self.speaker.say(
                                "Not flying just now, so there is no heading "
                                "to give."
                            )
                        if (pending_action in ("next", "previous")
                                and time.monotonic() - state.pending_action_since
                                > PENDING_ACTION_PATIENCE):
                            # Held for a moment first: a press caught during a
                            # brief gap is usually served by the next pass.
                            self.speaker.say(
                                "Not on the world map just now, so there are "
                                "no destinations to choose."
                            )
                            state.pending_action = None
                        time.sleep(0.15)
                        continue
                    menus.suspend()
                    self.note_capture_size(captured)
                    if state.surface is None:
                        observed = discover_surface(
                            self.pine, self.scanner, lambda: captured
                        )
                    else:
                        observed = refresh_surface(
                            self.pine, self.scanner, state.surface, lambda: captured
                        )
                    player = self.pine.read_vector3_many((observed.player_address,))[0]
                    observed = self.augment_local(observed, player)
                    state.memory_ready = True
                    if not getattr(observed, "liveness_confirmed", True):
                        # Say it once. The destinations are usable and teleport
                        # still verifies every write, but the table could not
                        # prove it belongs to this map, and the player should
                        # know that rather than infer it from a surprise.
                        self.speaker.say(
                            "Using this map's destinations without confirmation: "
                            "the game is not updating the check the guide "
                            "normally uses.",
                            once=True,
                        )
                    if wants_direction:
                        self.announce_direction(observed, player)
                    if pending_action in ("next", "previous"):
                        # Choosing somewhere to go needs nothing but the map
                        # and where the player is, so it is answered here
                        # rather than waiting for an objective that may never
                        # arrive.
                        self.cycle_destination(observed, player, pending_action)
                        state.pending_action = None
                        pending_action = None
                except MapNotReady:
                    state.memory_ready = False
                    fallback_analysis = self.analyze(captured)
                    if (
                        fallback_analysis is not None
                        and fallback_analysis.world_map_visible
                    ):
                        # Guidance does not need a coordinate table.  A live
                        # minimap is enough to follow arrow-to-marker pixels;
                        # memory discovery may attach later and enable
                        # teleport without interrupting that route.
                        observed = vision_world_surface()
                        player = None
                        if (pending_action in ("next", "previous")
                                and time.monotonic() - state.pending_action_since
                                > PENDING_ACTION_PATIENCE):
                            self.speaker.say(
                                "The map's destinations are not readable yet. "
                                "Keep the world map in view for a moment."
                            )
                            state.pending_action = None
                        if wants_direction:
                            # Honest about why, rather than silent: without a
                            # coordinate table there is no position to measure
                            # a distance or a heading from.
                            self.speaker.say(
                                "Position not readable yet, so I cannot say "
                                "which way to turn."
                            )
                    else:
                        state.ready_count = 0
                        state.ready_identity = None
                        state.missing_count += 1
                        if state.missing_count >= SURFACE_MISSING_CONFIRMATIONS:
                            if state.surface is not None:
                                self.speaker.say(
                                    "Dragon Adventure navigation closed; waiting for "
                                    "it to return.",
                                    once=True,
                                )
                            state.reset_surface()
                        time.sleep(0.35)
                        continue

                observed = self.name_surface(observed, captured_analysis)
                state.missing_count = 0
                state.surface = observed
                identity = observed.identity

                if state.active_identity is None:
                    if identity == state.ready_identity:
                        state.ready_count += 1
                    else:
                        state.ready_identity = identity
                        state.ready_count = 1
                    if state.ready_count < SURFACE_READY_CONFIRMATIONS:
                        time.sleep(0.2)
                        continue
                    self.reset_world_tracking()
                    state.active_identity = identity
                    state.objective = None
                    state.arrived = False
                    state.last_objective_check = 0.0
                    state.pending_objective_index = None
                    state.pending_objective_key = None
                    state.pending_objective_count = 0
                    state.pending_objective_frame_sequence = -1
                    state.objective_last_seen = 0.0
                    state.announced_event_wait = False
                    state.event_confirmation_count = 0
                    state.last_event_frame_sequence = -1
                    state.world_map_visible = False
                    state.visual_missing_count = 0
                    state.visual_ready_count = 0
                    if not observed.is_local and not observed.is_vision_only:
                        self.calibrator_for(observed)
                    self.record_geometry(observed)
                    self.announce_surface(observed)
                elif identity != state.active_identity:
                    self.reset_world_tracking()
                    state.active_identity = identity
                    state.blocked_identity = None
                    state.objective = None
                    state.arrived = False
                    state.last_objective_check = 0.0
                    state.announced_degraded = False
                    state.pending_objective_index = None
                    state.pending_objective_key = None
                    state.pending_objective_count = 0
                    state.pending_objective_frame_sequence = -1
                    state.objective_last_seen = 0.0
                    state.announced_event_wait = False
                    state.event_confirmation_count = 0
                    state.last_event_frame_sequence = -1
                    state.world_map_visible = False
                    state.visual_missing_count = 0
                    state.visual_ready_count = 0
                    self.announce_surface(observed)

                image = None if observed.is_local else captured
                analysis = None if image is None else captured_analysis

                # The minimap, not a resident coordinate table, decides when
                # world-map navigation is actually present.  Require separate
                # captured frames in both directions so loading/fade frames do
                # not start guidance or preserve a previous chapter's target.
                if not observed.is_local:
                    if self._visual_sequence != self._frame_sequence:
                        self._visual_sequence = self._frame_sequence
                        visible = bool(
                            analysis is not None and analysis.world_map_visible
                        )
                        if visible:
                            state.visual_ready_count += 1
                            state.visual_missing_count = 0
                            if (
                                not state.world_map_visible
                                and state.visual_ready_count
                                >= SURFACE_READY_CONFIRMATIONS
                            ):
                                had_target = state.objective is not None
                                self.reset_world_tracking()
                                state.world_map_visible = True
                                state.objective = None
                                state.pending_objective_key = None
                                state.pending_objective_count = 0
                                state.pending_objective_frame_sequence = -1
                                state.objective_last_seen = 0.0
                                state.arrived = False
                                state.event_confirmation_count = 0
                                state.last_event_frame_sequence = -1
                                if had_target:
                                    self.speaker.say(
                                        "World map detected again; reacquiring "
                                        "the current objective."
                                    )
                        else:
                            paused_holding_route = (
                                self.pine.status() == 1
                                and state.objective is not None
                                and state.objective.has_direction
                            )
                            if paused_holding_route:
                                # PCSX2 can dim a paused frame below the arrow
                                # detector's white threshold.  Pausing is also
                                # the required precondition for teleport, so do
                                # not erase a route solely because of that
                                # expected visual change.
                                state.visual_missing_count = 0
                            else:
                                state.visual_ready_count = 0
                                state.visual_missing_count += 1
                                if (
                                    state.visual_missing_count
                                    >= SURFACE_MISSING_CONFIRMATIONS
                                ):
                                    if state.world_map_visible:
                                        self.speaker.say(
                                            "Minimap closed; waiting for the world "
                                            "map to return.",
                                            once=True,
                                        )
                                    state.world_map_visible = False
                                    self.reset_world_tracking()
                                    state.objective = None
                                    state.pending_objective_key = None
                                    state.pending_objective_count = 0
                                    state.pending_objective_frame_sequence = -1
                                    state.objective_last_seen = 0.0
                                    state.arrived = False
                                    state.event_confirmation_count = 0
                                    state.last_event_frame_sequence = -1
                    if not state.world_map_visible:
                        time.sleep(0.15)
                        continue

                # Learn this map's HUD projection from the player arrow.
                was_confident = False
                calibrator = (
                    None
                    if observed.is_local or observed.is_vision_only
                    else self.calibrator_for(observed)
                )
                if calibrator is not None and calibrator.calibration is not None:
                    was_confident = calibrator.calibration.confident
                if image is not None:
                    self.observe_arrow(observed, player, image, analysis)
                    self.survey_map(observed, image, analysis)
                if calibrator is not None and calibrator.calibration is not None:
                    now_confident = calibrator.calibration.confident
                    if now_confident and not was_confident:
                        winsound.PlaySound(
                            calibrated_tone(),
                            winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                        )
                        self.speaker.say(
f"{observed.display_name} calibrated."
                        )
                        self.persist_calibration(observed)
                    elif now_confident:
                        self.persist_calibration(observed)
                # Screen-space guidance does not wait for this calibration.
                # It is learned in parallel solely for optional teleport
                # conversion from minimap pixels to writable world coordinates.

                projection = self.projection_for(observed, player)

                # Resolve the objective.
                needs_objective = state.objective is None
                story_scan_pending = (
                    self.selector.casefold() == "objective"
                    and (
                        needs_objective
                        or not state.objective.confirmed
                        or state.pending_objective_count > 0
                    )
                )
                recheck_interval = (
                    CAPTURE_INTERVAL
                    if self.selector.casefold() == "objective"
                    else OBJECTIVE_RECHECK_SECONDS
                )
                due = (
                    time.monotonic() - state.last_objective_check
                    >= recheck_interval
                )
                if observed.is_local:
                    chosen = self.selected_location(observed, player)
                    if chosen is not None:
                        if not state.announced_selection:
                            self.speaker.say(
                                f"{chosen.label}, "
                                f"{distance_to(player, chosen):.0f} units away"
                                + (
                                    f", 1 of {len(observed.locations)}."
                                    if len(observed.locations) == 1
                                    else f", 1 of {len(observed.locations)}. "
                                    "Press N for the next one."
                                )
                            )
                            state.announced_selection = True
                        state.objective = Objective(
                            chosen, CONFIRMED, "nearby character in this area"
                        )
                elif (needs_objective or due) and not (
                    self.pine.status() == 1
                    and state.objective is not None
                    and state.objective.confirmed
                ):
                    state.last_objective_check = time.monotonic()
                    try:
                        resolved = resolve_selector(
                            self.selector,
                            observed,
                            player,
                            projection,
                            image,
                            analysis,
                        )
                        if not observed.requires_world_return:
                            resolved = self.stabilize_story_objective(
                                resolved,
                                frame_sequence=self._frame_sequence,
                            )
                    except (ObjectiveNotReady, ValueError) as error:
                        self.speaker.say(
                            f"Waiting for the current story objective: {error}",
                            once=True,
                        )
                        time.sleep(0.35)
                        continue
                    self.update_objective(resolved)

                if state.objective is None:
                    time.sleep(0.3)
                    continue

                if not state.objective.has_direction:
                    time.sleep(0.2)
                    continue
                target = state.objective.location
                if (
                    not observed.is_local
                    and state.objective.screen_target is not None
                ):
                    target = self._screen_location(observed, player, state.objective)
                if state.destination_chosen:
                    # The player picked this with N or B, so it is what T means
                    # and what G reports. Only an explicit choice overrides the
                    # story marker -- the guide never promotes its own starting
                    # guess to a decision the player did not make.
                    #
                    # The guidance tones are untouched: on a world map they
                    # follow the minimap marker by a separate path, so choosing
                    # a destination changes where T goes without changing what
                    # is being flown toward.
                    picked = state.chosen_location
                    if picked is not None:
                        target = picked

                # Armed local-route teleport, completed once back on a world map.
                if state.pending_world_teleport and not observed.is_local:
                    if self.pine.status() != 1:
                        if not state.pending_pause_notice:
                            self.speaker.say(
                                "Armed teleport is ready. Pause PCSX2 manually; "
                                "the transaction will run while the CPU thread "
                                "is stopped."
                            )
                            state.pending_pause_notice = True
                    else:
                        state.pending_pause_notice = False
                        if target is None:
                            state.pending_world_teleport = False
                            self.speaker.say(
                                "Armed teleport cancelled: the minimap-to-world "
                                "scale is not learned yet. Resume and fly in two "
                                "directions, then try again."
                            )
                            time.sleep(0.25)
                            continue
                        try:
                            count = teleport(
                                self.pine,
                                observed,
                                target,
                                self._rediscover(player),
                            )
                            state.pending_world_teleport = False
                            player = self.pine.read_vector3_many(
                                (observed.player_address,)
                            )[0]
                            self.speaker.say(
                                "Armed teleport completed using "
                                f"{count} live position mirrors. Resume PCSX2 "
                                "manually."
                            )
                            state.last_arrow = None
                            state.last_arrow_world = None
                            self.calibrator_for(observed).reset_anchor()
                            time.sleep(0.25)
                            continue
                        except (MapNotReady, RuntimeError, TimeoutError) as error:
                            state.pending_world_teleport = False
                            state.pending_pause_notice = False
                            state.blocked_identity = identity
                            self.speaker.say(
                                f"Armed teleport cancelled: {error}. Teleport is "
                                "blocked until the surface changes."
                            )
                            time.sleep(0.35)
                            continue

                if player is not None:
                    self.track_visit(observed, player)

                action = state.pending_action
                state.pending_action = None
                if action in ("free", "story", "none"):
                    if not self.classify_visit(observed, action, player):
                        self.speaker.say("Nothing to record.")
                    time.sleep(0.15)
                    continue
                if action is not None and not observed.is_local:
                    if action in ("next", "previous"):
                        # Cycling was refused while following the story marker,
                        # which left no way to ask about anything else on the
                        # map. It now always picks, and G reports whatever is
                        # picked. The tones keep following the story objective;
                        # changing what they steer to is a separate decision.
                        self.cycle_destination(observed, player, action)
                        if self.selector.casefold() != "objective":
                            state.objective = None
                    elif self.selector.casefold() == "objective":
                        if action == "repeat" and state.objective is not None:
                            census = state.inventory.census
                            self.speaker.say(
                                f"{census.describe()}. "
                                f"Guiding to {state.objective.label}."
                            )
                    else:
                        self.cycle_destination(observed, player, action)
                        state.objective = None
                    time.sleep(0.15)
                    continue

                hotkey = hotkeys.poll()
                if hotkey:
                    if state.blocked_identity == identity:
                        self.speaker.say(
                            f"{hotkey} teleport ignored: a previous transaction "
                            "failed here. Change maps before retrying."
                        )
                        time.sleep(0.25)
                        continue
                    if observed.requires_world_return:
                        state.pending_world_teleport = not state.pending_world_teleport
                        state.pending_pause_notice = False
                        word = "armed" if state.pending_world_teleport else "cancelled"
                        self.speaker.say(
                            f"{hotkey} local route teleport {word}. Press R1 "
                            "normally; after the world map loads, pause PCSX2 "
                            "manually to complete the move."
                        )
                        time.sleep(0.25)
                        continue
                    # An unconfirmed destination is no longer a reason to
                    # refuse.  This gate existed to stop the mod *guessing* a
                    # destination and moving the player there as if it were the
                    # story objective; a destination picked with N or B is the
                    # player's own decision, and refusing it just made the
                    # feature useless on every map whose objective cannot be
                    # identified -- which is all of them.  The safety that
                    # matters is untouched: PCSX2 must still be paused, and the
                    # write is still verified and rolled back on failure.
                    if self.pine.status() != 1:
                        self.speaker.say(
                            f"{hotkey} teleport not written: pause PCSX2 "
                            "manually, then press the teleport hotkey again."
                        )
                        time.sleep(0.25)
                        continue
                    if target is None:
                        self.speaker.say(
                            f"{hotkey} teleport not written: keep flying until "
                            "the minimap-to-world scale is learned."
                        )
                        time.sleep(0.25)
                        continue
                    try:
                        count = teleport(
                            self.pine,
                            observed,
                            target,
                            self._rediscover(player),
                        )
                        player = self.pine.read_vector3_many(
                            (observed.player_address,)
                        )[0]
                        if state.destination_chosen:
                            note = ", the destination you chose."
                        elif state.objective is not None and state.objective.confirmed:
                            note = "."
                        else:
                            note = ", the story marker."
                        spoken = (
                            state.chosen_name
                            if state.destination_chosen and state.chosen_name
                            else target.label
                        )
                        self.speaker.say(
                            f"{hotkey} teleport: moved to {spoken}{note}"
                        )
                        if not observed.is_local:
                            state.last_arrow = None
                            state.last_arrow_world = None
                            self.calibrator_for(observed).reset_anchor()
                        time.sleep(0.25)
                        continue
                    except (MapNotReady, RuntimeError, TimeoutError) as error:
                        self.speaker.say(f"{hotkey} teleport deferred: {error}")
                        state.blocked_identity = identity
                        state.reset_surface()
                        state.ready_count = 0
                        state.ready_identity = None
                        time.sleep(0.35)
                        continue

                # World-map guidance is purely the live minimap vector.  It
                # neither selects nor approaches a coordinate-table entry.
                if not observed.is_local and state.objective.screen_target is not None:
                    offset = self._screen_offset(state.objective, image)
                    if offset is None:
                        self.speaker.say(
                            "Tracking the minimap; move briefly so the player "
                            "arrow can be identified.",
                            once=True,
                        )
                        time.sleep(0.2)
                        continue
                    delta_x, delta_y, distance = offset
                    overlap = distance <= max(
                        8.0, 0.012 * max(image.width, image.height)
                    )
                    event_description = (
                        analysis.event_description if analysis is not None else False
                    )
                    if self._screen_arrival_confirmed(
                        overlap,
                        event_description,
                        frame_sequence=self._frame_sequence,
                    ):
                        state.announced_event_wait = False
                        if not state.arrived:
                            winsound.PlaySound(
                                arrival_tone(),
                                winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                            )
                            self.speaker.say(
                                f"On {state.objective.label}. Press Cross."
                            )
                            state.arrived = True
                        time.sleep(0.25)
                        continue

                    if overlap:
                        # The arrival chime and Cross prompt are enough. A
                        # hovering arrow can cross this boundary repeatedly;
                        # narrating each crossing disrupted the approach.
                        time.sleep(0.12)
                        continue

                    if state.arrived:
                        self.speaker.say(
                            f"Off {state.objective.label}; guidance resumed."
                        )
                    state.arrived = False
                    state.announced_event_wait = False
                    state.event_confirmation_count = 0
                    state.last_event_frame_sequence = -1

                    scale = max(distance, 1.0)
                    pan = delta_x / scale
                    # Screen y grows downward; moving toward the top of the
                    # minimap is forward/north and therefore raises pitch.
                    frequency = 650.0 - 260.0 * delta_y / scale
                    winsound.PlaySound(
                        tone(
                            frequency,
                            pan,
                            degraded=not state.objective.confirmed,
                        ),
                        winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                    )
                    time.sleep(max(0.08, min(0.65, distance / 180.0)))
                    continue

                # Explicit table selectors and local areas retain world-space
                # guidance as a secondary diagnostic/local navigation mode.
                delta_x = target.x - player[0]
                delta_z = target.z - player[2]
                distance = distance_to(player, target)

                if observed.requires_world_return:
                    if not state.arrived:
                        winsound.PlaySound(
                            arrival_tone(),
                            winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                        )
                        self.speaker.say(
                            "No verified local story interaction is active. "
                            "Press R1 to return to the world map."
                        )
                        state.arrived = True
                    time.sleep(0.25)
                    continue

                # The table's radius is the map's detection circle, not a spot
                # where the game will accept Cross -- on Earth it reaches 300
                # world units.  Guidance therefore continues all the way to the
                # coordinate itself; stopping at the circle's edge left the
                # player standing in open space with nothing left to follow.
                # The sphere is what the game tests, so arrival is judged in
                # three dimensions.  ``reach`` is how close the player has to
                # get horizontally at the altitude they are actually flying;
                # it is None when this point cannot be entered from up here.
                reach = horizontal_reach(target, player[1])
                final_threshold = min(
                    FINAL_APPROACH_UNITS, reach if reach is not None else target.radius
                )
                inside_trigger = within_trigger(player, target)

                # Planar distance alone is not arrival.  The overworld is flown
                # at a resting altitude, and hovering off that plane leaves the
                # player horizontally on the point with the button doing
                # nothing.  The altitude is learned from this map's own flight,
                # so no per-map constant is involved.
                altitude = None
                altitude_offset = None
                if not observed.is_local:
                    altitude = self.altitude_for(observed)
                    altitude.observe(player[1])
                    altitude_offset = altitude.offset(player[1])
                level = altitude is None or altitude.aligned(player[1])

                # Advisory, never blocking.  Observed altitudes vary more than
                # the recorded captures suggested (-170 in the corpus, but -121
                # and -154 in live sessions), so there is not enough evidence to
                # refuse an arrival over it.  Say it and let the player judge.
                if distance <= final_threshold and not level:
                    if not state.announced_altitude:
                        direction = "descend" if altitude_offset > 0 else "climb"
                        self.speaker.say(
f"On {target.label}. If Cross does nothing, "
                            f"{direction} {abs(altitude_offset):.0f}."
                        )
                        state.announced_altitude = True
                elif level:
                    state.announced_altitude = False

                event_description = (
                    analysis is not None
                    and not observed.is_local
                    and analysis.event_description
                )
                if (
                    distance <= final_threshold
                    and not observed.is_local
                    and not event_description
                ):
                    if not state.announced_event_wait:
                        self.speaker.say(
                            f"At {target.label}. Waiting for the map-event "
                            "description before prompting Cross."
                        )
                        state.announced_event_wait = True
                    time.sleep(0.25)
                    continue
                if distance <= final_threshold:
                    state.announced_event_wait = False
                    if not state.arrived:
                        winsound.PlaySound(
                            arrival_tone(),
                            winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                        )
                        self.speaker.say(
f"On {target.label}. Press Cross."
                        )
                        state.arrived = True
                        state.last_callout = None
                    time.sleep(0.35)
                    continue
                if state.arrived:
                    # Drifted back off the point; resume guiding rather than
                    # leaving the player with a stale "press Cross".
                    self.speaker.say(f"Off the point, {distance:.0f} units away.")
                state.arrived = False
                state.announced_event_wait = False

                if inside_trigger:
                    if not state.announced_inside:
                        self.speaker.say(
f"Inside {target.label}. {distance:.0f} units."
                        )
                        state.announced_inside = True
                        state.last_callout = distance
                    # Count down so progress is audible without watching a HUD.
                    # Announce only the lowest threshold already crossed, and
                    # only when it is lower than the last one announced: a live
                    # run repeated "100 units" three times while manoeuvring,
                    # and starting mid-range used to read out every threshold
                    # above the player in one burst.
                    crossed = [s for s in CLOSING_CALLOUTS if distance <= s]
                    if crossed:
                        step = min(crossed)
                        if state.last_callout is None or step < state.last_callout:
                            self.speaker.say(f"{step} units.")
                            state.last_callout = step
                elif state.announced_inside:
                    state.announced_inside = False
                    state.last_callout = None

                scale = max(distance, 1.0)
                if (
                    observed.is_local
                    and observed.local_right is not None
                    and observed.local_forward is not None
                ):
                    right = (
                        delta_x * observed.local_right[0]
                        + delta_z * observed.local_right[1]
                    )
                    forward = (
                        delta_x * observed.local_forward[0]
                        + delta_z * observed.local_forward[1]
                    )
                    pan = right / scale
                    frequency = 650.0 + 260.0 * forward / scale
                else:
                    pan = delta_x / scale
                    frequency = 650.0 + 260.0 * delta_z / scale

                winsound.PlaySound(
                    tone(frequency, pan, degraded=not state.objective.confirmed),
                    winsound.SND_MEMORY | winsound.SND_NODEFAULT,
                )
                if inside_trigger:
                    # Fine approach: pulse fast and keep resolution proportional
                    # to what is left, so the last few units stay steerable.
                    delay = max(0.05, min(0.3, distance / (final_threshold * 12.0)))
                else:
                    delay = max(0.08, min(0.9, distance / 1_600.0))
                time.sleep(delay)
        finally:
            hotkeys.close()
            winsound.PlaySound(None, 0)
            self.speaker.silence()
            if close_speaker:
                self.speaker.close()


def waiting_guide(selector: str, stop_event=None, speaker=None) -> None:
    """Stay alive while PCSX2, the game, or a surface is loading."""
    from pine_client import PineClient, PineError

    speaker = speaker or Speaker()
    speaker.say("Accessibility guide loaded; waiting for DBZ BT2 in PCSX2.")
    store = default_store()
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                from .pcsx2 import active_connection
                connection = active_connection(os.environ.get("BT2_EMULATOR",""), os.environ.get("BT2_PORTABLE")=="1")
                os.environ["BT2_EMULATOR_PID"] = str(connection["pid"])
                with PineClient(port=connection["port"],timeout=10.0) as pine:
                    try:
                        validate_game(pine)
                    except RuntimeError:
                        speaker.say("Waiting for the USA DBZ BT2 game to start.", once=True)
                        if stop_event is None:
                            time.sleep(1.0)
                        else:
                            stop_event.wait(1.0)
                        continue
                    speaker.say("DBZ BT2 detected. Waiting for Dragon Adventure.")
                    Guide(pine, selector, store, speaker).run(stop_event, close_speaker=False)
            except (ConnectionError, OSError, PineError) as error:
                speaker.say("Waiting for PCSX2's game connection. " + str(error), once=True)
                if stop_event is None:
                    time.sleep(1.0)
                else:
                    stop_event.wait(1.0)
            except Exception as error:
                # Unfamiliar host/map states should remain visible and retry
                # rather than terminating the resident desktop worker.
                speaker.say(
                    f"Guide recovered from {type(error).__name__}: "
                    f"{str(error).rstrip('.')}. Retrying.",
                    once=True,
                )
                if stop_event is None:
                    time.sleep(1.0)
                else:
                    stop_event.wait(1.0)
    finally:
        speaker.silence()
        speaker.close()
