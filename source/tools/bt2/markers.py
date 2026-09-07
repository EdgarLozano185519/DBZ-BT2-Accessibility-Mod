"""Marker census and optional minimap-to-world conversion helpers.

The coordinate table lists every destination a map has ever had, including the
ones unavailable in the current chapter -- standing on those and pressing Cross
does nothing, which made most of the table worse than useless as a list of
places to go.

The resident objective guide follows marker and player-arrow screen positions
directly. It does not use the pairings in this module to choose or steer toward
a story target. These helpers remain for diagnostics, explicit table selection,
and the optional conversion needed to write a teleport.

A marker is already a screen position, so direct audio guidance only subtracts
the player-arrow position. A projection is needed solely when that pixel vector
must become writable world coordinates. In that optional path, a marker sitting
on a table entry can take the entry's coordinates, while an unmatched marker is
converted by inverting the live movement projection.

That second case is not an edge case -- it is the story objective. On a live
map the red marker sat 41 px from the nearest table point and 45 px from the
next, on opposite sides of each, with no linear fit placing it on either. The
table can name free events but it does not contain the objective, so requiring
a table match guided to every free event and never to the story.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .navigation import project_with, unproject_with
from .vision import Blob, analyze_frame

# A marker is matched to the table point that projects nearest to it.  Beyond
# this the pairing is not trustworthy; measured fits land within about a pixel.
MATCH_TOLERANCE_PX = 12.0
# Used for a marker with no table entry, where there is no recorded radius.
# The observed points range from 200 to 300, so this is mid-range rather than
# optimistic -- an over-large radius would announce arrival too early.
DEFAULT_MARKER_RADIUS = 220.0
# Synthetic destinations are indexed below zero so they can never be confused
# with a table entry, including in anything keyed by point index.
FIRST_SYNTHETIC_INDEX = -1


@dataclass(frozen=True)
class Census:
    """How many markers the map is drawing, and of which kinds."""

    red: tuple[Blob, ...] = ()
    yellow: tuple[Blob, ...] = ()
    other: tuple[Blob, ...] = ()

    @property
    def all(self) -> tuple[Blob, ...]:
        return self.red + self.yellow + self.other

    @property
    def total(self) -> int:
        return len(self.all)

    def describe(self) -> str:
        if not self.total:
            return "no destinations showing"
        parts = [f"{self.total} destination" + ("s" if self.total != 1 else "")]
        if len(self.red) == 1:
            parts.append("1 story")
        elif self.red:
            parts.append(f"{len(self.red)} story")
        if self.yellow:
            parts.append(f"{len(self.yellow)} free")
        return ", ".join(parts)


def take_census(image=None, analysis=None) -> Census:
    """Count the markers drawn on the minimap, split by kind."""
    if analysis is None and image is not None:
        analysis = analyze_frame(image)
    if analysis is None:
        return Census()
    markers = list(analysis.markers)
    red = tuple(blob for blob in markers if blob.is_red)
    yellow = tuple(
        blob for blob in markers if not blob.is_red and blob.is_yellow
    )
    other = tuple(
        blob for blob in markers if not blob.is_red and not blob.is_yellow
    )
    return Census(red=red, yellow=yellow, other=other)


@dataclass
class _SeenMarker:
    anchor: tuple[float, float]
    blob: Blob
    frames: list[int] = field(default_factory=list)
    confirmed: bool = False
    # Consecutive observed frames in which a confirmed marker was not seen.
    missing: int = 0


class MinimapInventory:
    """Keep stable destinations for one visit, despite animation and occlusion.

    Admission requires four sightings in six distinct frames near the original
    position. Moving scenery cannot drag a track across the image. Once found,
    destinations stay in the census until navigation closes or the map changes;
    an arrow covering a dot does not remove a destination from the list.
    """

    WINDOW = 6
    REQUIRED_SIGHTINGS = 4
    # How many consecutive frames a confirmed destination must be absent before
    # it is believed gone. Generous on purpose: the player's arrow sits over a
    # dot for a second or two at a time, and losing destinations to that was
    # the reason confirmed tracks were made permanent in the first place. But
    # permanent was too strong -- finishing a story event changes the markers
    # while the map stays the same, and the guide went on offering the old set.
    # At roughly four frames a second this is about seven seconds of absence.
    LOST_FRAMES = 30

    def __init__(self):
        self._tracks: list[_SeenMarker] = []
        self._last_sequence = None
        self.frames = 0

    def observe(self, analysis, frame_sequence: int) -> Census:
        if frame_sequence == self._last_sequence:
            return self.census
        self._last_sequence = frame_sequence
        self.frames += 1
        radius = max(4.0, max(analysis.width, analysis.height) * 0.006)
        claimed = set()
        for blob in analysis.markers:
            nearest = None
            distance = radius
            for index, track in enumerate(self._tracks):
                if index in claimed:
                    continue
                offset = math.hypot(
                    blob.x - track.anchor[0] * analysis.width,
                    blob.y - track.anchor[1] * analysis.height,
                )
                if offset <= distance:
                    nearest, distance = index, offset
            if nearest is None:
                nearest = len(self._tracks)
                self._tracks.append(_SeenMarker(
                    (blob.x / analysis.width, blob.y / analysis.height), blob
                ))
            claimed.add(nearest)
            track = self._tracks[nearest]
            track.frames = [
                frame for frame in track.frames if frame > self.frames - self.WINDOW
            ] + [self.frames]
            if not track.confirmed:
                track.blob = blob
                track.confirmed = len(track.frames) >= self.REQUIRED_SIGHTINGS

        for index, track in enumerate(self._tracks):
            if not track.confirmed:
                continue
            track.missing = 0 if index in claimed else track.missing + 1

        self._tracks = [
            track for track in self._tracks
            if (track.confirmed and track.missing <= self.LOST_FRAMES)
            or (not track.confirmed
                and track.frames[-1] > self.frames - self.WINDOW)
        ]
        return self.census

    @property
    def settled(self) -> bool:
        return self.frames >= self.WINDOW and self.census.total > 0

    @property
    def census(self) -> Census:
        blobs = [track.blob for track in self._tracks if track.confirmed]
        return Census(
            red=tuple(blob for blob in blobs if blob.is_red),
            yellow=tuple(blob for blob in blobs if not blob.is_red and blob.is_yellow),
            other=tuple(blob for blob in blobs if not blob.is_red and not blob.is_yellow),
        )


@dataclass(frozen=True)
class MarkerLocation:
    """A destination that exists on the map but not in the coordinate table.

    Carries the same fields a table entry does, so guidance, arrival and
    teleport treat it identically.  Its coordinates come from inverting the
    map's projection, which is less exact than a recorded coordinate -- a live
    check put a known point out by about 100 world units -- so it is accurate
    enough to fly to and not to land on blind.
    """

    index: int
    x: float
    y: float
    z: float
    radius: float
    name: str
    # Synthetic world-map targets navigate in the flight plane.  Providing the
    # same protocol as memory.Location prevents screen-derived objectives from
    # crashing distance, arrival, and teleport code.
    use_y: bool = False

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True)
class Destination:
    """An available destination: a marker paired with its world coordinates."""

    location: object
    kind: str
    marker: Blob

    @property
    def is_story(self) -> bool:
        return self.kind == "story"


def destinations(surface, census: Census, affine) -> tuple[Destination, ...]:
    """Pair each drawn marker with the place it refers to.

    Returns story destinations first, so the guide reaches for the objective
    before anything optional. A marker on a table entry uses that entry's exact
    coordinates; a marker on nothing gets its own, read back out of the
    projection. Without a projection nothing can be placed at all, and an empty
    result says exactly that rather than guessing.
    """
    if affine is None or not census.total:
        return ()

    projected = [
        (location, project_with(affine, location.x, location.z))
        for location in surface.locations
    ]
    radius = DEFAULT_MARKER_RADIUS
    if surface.locations:
        ordered = sorted(location.radius for location in surface.locations)
        radius = ordered[len(ordered) // 2]

    used: set[int] = set()
    found: list[Destination] = []
    synthetic = FIRST_SYNTHETIC_INDEX
    for kind, blobs in (("story", census.red), ("free", census.yellow),
                        ("free", census.other)):
        for blob in blobs:
            best = None
            best_distance = None
            for location, (screen_x, screen_y) in projected:
                if location.index in used:
                    continue
                distance = (
                    (blob.x - screen_x) ** 2 + (blob.y - screen_y) ** 2
                ) ** 0.5
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best = location
            if best is not None and best_distance is not None and (
                best_distance <= MATCH_TOLERANCE_PX
            ):
                used.add(best.index)
                found.append(Destination(location=best, kind=kind, marker=blob))
                continue

            # No table entry under this marker.  It is still a real place, so
            # invert the projection and go there.
            world = unproject_with(affine, blob.x, blob.y)
            if world is None:
                continue
            name = "story objective" if kind == "story" else "free event"
            found.append(
                Destination(
                    location=MarkerLocation(
                        index=synthetic,
                        x=world[0],
                        y=0.0,
                        z=world[1],
                        radius=radius,
                        name=name,
                    ),
                    kind=kind,
                    marker=blob,
                )
            )
            synthetic -= 1
    return tuple(found)
