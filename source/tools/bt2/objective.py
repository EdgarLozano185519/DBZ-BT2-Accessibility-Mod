"""Choose the story target directly from the live minimap.

Red remains the strongest known story-event signal. Stable non-red outliers and
singletons are temporal candidates so palette variants do not make the guide
silent. Every accepted world target carries its normalized screen position;
matching it to a coordinate table is optional metadata, never a prerequisite
for guidance or arrival.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calibration import AnchoredProjection
from .memory import Location, distance_to
from .surface import Surface
from .vision import Blob, analyze_frame, distinct_marker, story_markers

# Confirmed: a target survived temporal minimap confirmation.
CONFIRMED = "confirmed"
# A visually plausible non-red highlight.  It becomes confirmed only after the
# guide observes the same screen target in consecutive frames.
CANDIDATE = "candidate"
# Unconfirmed: the destination is real geometry, but which point the story
# wants could not be read from the HUD.
UNCONFIRMED = "unconfirmed"

MARKER_MATCH_TOLERANCE = 0.022  # normalized to the window's larger edge


@dataclass(frozen=True)
class Objective:
    # ``None`` means that the HUD did not yet yield a safe story destination.
    # An explicit "nearest" or numbered selector still always has a location.
    location: object | None
    confidence: str
    method: str
    # Where the highlighted marker sits on screen, normalized to the window.
    # This is the primary world-map route; location is optional metadata.
    screen_target: tuple[float, float] | None = None

    @property
    def confirmed(self) -> bool:
        return self.confidence == CONFIRMED and self.has_direction

    @property
    def has_direction(self) -> bool:
        return self.location is not None or self.screen_target is not None

    @property
    def label(self) -> str:
        return self.location.label if self.location is not None else "story objective"

    @property
    def stable_key(self) -> tuple:
        """Identity suitable for temporal confirmation.

        Screen targets are quantized coarsely enough to absorb detector jitter
        while remaining much smaller than the spacing between map markers.
        """
        if self.screen_target is not None:
            return (
                "screen",
                round(self.screen_target[0], 2),
                round(self.screen_target[1], 2),
            )
        if self.location is not None:
            return ("location", self.location.index)
        return ("none",)

    def same_target(self, other: Objective | None) -> bool:
        """A few jittering pixels do not make a new destination.

        Rounded screen keys straddle arbitrary boundaries; comparing positions
        directly avoids resetting arrival and speaking on each such crossing.
        """
        if other is None:
            return False
        if self.screen_target is not None and other.screen_target is not None:
            return sum(
                (first - second) ** 2
                for first, second in zip(self.screen_target, other.screen_target)
            ) <= 0.012 ** 2
        if self.location is not None and other.location is not None:
            return self.location.index == other.location.index
        return not self.has_direction and not other.has_direction


def _projected_points(
    surface: Surface, projection: AnchoredProjection, width: int, height: int
) -> list[tuple[int, float, float]]:
    points = []
    for index, location in enumerate(surface.locations):
        screen_x, screen_y = projection.project_to_window(
            location.x, location.z, width, height
        )
        points.append((index, screen_x, screen_y))
    return points


def _match_markers(
    blobs: list[Blob],
    projected: list[tuple[int, float, float]],
    tolerance_pixels: float,
) -> list[tuple[Blob, int, float]]:
    matches = []
    for blob in blobs:
        best_index = None
        best_distance = None
        for index, screen_x, screen_y in projected:
            distance = ((blob.x - screen_x) ** 2 + (blob.y - screen_y) ** 2) ** 0.5
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_index = index
        if best_index is not None and best_distance is not None:
            if best_distance <= tolerance_pixels:
                matches.append((blob, best_index, best_distance))
    return matches


def objective_from_analysis(
    analysis,
    surface: Surface,
    projection: AnchoredProjection | None = None,
) -> Objective:
    """Resolve a target from the minimap without requiring map coordinates.

    A table match is retained only as optional metadata for explicit commands
    and teleport diagnostics.  Directional guidance always has the normalized
    marker position and can therefore begin as soon as the player arrow is
    tracked, even on a map whose table has never been seen.
    """
    blobs = list(analysis.markers)
    projected = (
        _projected_points(surface, projection, analysis.width, analysis.height)
        if projection is not None
        else []
    )
    tolerance = MARKER_MATCH_TOLERANCE * max(analysis.width, analysis.height)
    matches = _match_markers(blobs, projected, tolerance) if projected else []

    def matched(candidates):
        chosen = [
            (blob, index, distance)
            for blob, index, distance in matches
            if blob in candidates
        ]
        return chosen

    def objective_for(
        blob: Blob, method: str, confidence: str = CONFIRMED
    ) -> Objective:
        paired = matched([blob])
        location = surface.locations[paired[0][1]] if len(paired) == 1 else None
        return Objective(
            location,
            confidence,
            method,
            (blob.x / analysis.width, blob.y / analysis.height),
        )

    # Red is the strongest known semantic signal.  It is not the only one:
    # stable singletons and hue outliers cover maps/chapters that highlight an
    # objective differently without substituting a table guess.
    red = story_markers(blobs)
    if len(red) == 1:
        return objective_for(red[0], "red minimap story marker")
    if len(red) > 1:
        return Objective(
            None,
            UNCONFIRMED,
            f"{len(red)} red minimap markers visible; waiting for one route",
        )

    # A world-map frame has a small marker set.  Dozens of candidates indicate
    # scene art or an overlay in the broad ROI, not a usable minimap.
    if len(blobs) > 12:
        return Objective(
            None,
            UNCONFIRMED,
            "the minimap region is obscured by another screen",
        )

    # At contact the player arrow covers the red marker while the event banner
    # appears.  Do not reinterpret an unrelated coloured speck as a new route;
    # the temporal guide retains the already-verified target for this case.
    if analysis.event_description:
        return Objective(
            None,
            UNCONFIRMED,
            "objective marker is covered at the active event",
        )

    odd = distinct_marker(blobs)
    if odd is not None:
        return objective_for(
            odd,
            "minimap marker drawn unlike the others",
            CANDIDATE,
        )
    if len(blobs) == 1:
        return objective_for(
            blobs[0], "only visible minimap destination", CANDIDATE
        )
    if not blobs:
        detail = "no minimap markers were visible"
    else:
        detail = "minimap destinations are visible but none is uniquely highlighted"
    return Objective(None, UNCONFIRMED, detail)


def objective_from_image(
    image,
    surface: Surface,
    player: tuple[float, float, float],
    projection: AnchoredProjection | None,
) -> Objective:
    """Compatibility wrapper for one-shot commands and offline tests."""
    return objective_from_analysis(analyze_frame(image), surface, projection)


def resolve_objective(
    surface: Surface,
    player: tuple[float, float, float],
    projection: AnchoredProjection | None,
    image=None,
    analysis=None,
) -> Objective:
    if surface.requires_world_return:
        return Objective(
            surface.locations[0],
            CONFIRMED,
            "R1 return to the world-map story route",
        )
    if surface.is_local:
        return Objective(
            surface.locations[0], CONFIRMED, "authored local interaction transform"
        )
    if analysis is None and image is not None:
        analysis = analyze_frame(image)
    if analysis is None:
        return Objective(
            None,
            UNCONFIRMED,
            "no HUD capture available; waiting to read the minimap",
        )
    return objective_from_analysis(analysis, surface, projection)


def resolve_selector(
    selector: str,
    surface: Surface,
    player: tuple[float, float, float],
    projection: AnchoredProjection | None,
    image=None,
    analysis=None,
) -> Objective:
    normalized = selector.casefold()
    if normalized == "objective":
        return resolve_objective(surface, player, projection, image, analysis)
    if normalized == "nearest":
        nearest = min(
            surface.locations, key=lambda location: distance_to(player, location)
        )
        return Objective(nearest, UNCONFIRMED, "nearest coordinate-table point")
    try:
        index = int(selector)
    except ValueError as error:
        raise ValueError(
            "target must be a point number, 'objective', or 'nearest'"
        ) from error
    if not 1 <= index <= len(surface.locations):
        raise ValueError(
            f"target point must be between 1 and {len(surface.locations)} on this map"
        )
    return Objective(
        surface.locations[index - 1], UNCONFIRMED, f"explicit selector {selector}"
    )
