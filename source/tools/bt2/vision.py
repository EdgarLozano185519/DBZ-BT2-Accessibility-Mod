"""Vectorized HUD reading: markers, the player arrow, and the navigation HUD.

All detection is numpy over whole masks rather than per-pixel Python, which
matters because an uncalibrated map has no prior to restrict the search area.

Everything here takes a PIL image and returns plain values, so the offline
corpus can exercise it against recorded screenshots.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import math
import sys
from dataclasses import dataclass

import numpy as np

from .memory import ObjectiveNotReady

try:  # scipy gives a fast connected-component labeller when present.
    from scipy import ndimage as _ndimage
except (ImportError,OSError):  # pragma: no cover - exercised only without scipy
    _ndimage = None


@dataclass(frozen=True)
class Blob:
    """A compact HUD element in pixel coordinates."""

    x: float
    y: float
    width: int
    height: int
    pixels: int
    red: float
    green: float
    blue: float
    elongation: float = 0.0

    @property
    def is_red(self) -> bool:
        """Whether this is the red main-story marker documented for BT2.

        This is evaluated *after* compact marker detection, not against every
        red pixel on the screen.  The thresholds retain the dimmest recorded
        story marker (mean RGB 76, 0, 0) while rejecting the yellow free-event
        markers that occupy the same map.
        """
        return (
            self.red >= 70.0
            and self.red - self.green >= 20.0
            and self.red >= self.green * 1.35
            and self.red >= self.blue * 1.25
        )

    @property
    def is_yellow(self) -> bool:
        return (
            self.red >= 90.0
            and self.green >= 70.0
            and self.blue <= min(self.red, self.green) * 0.72
            and abs(self.red - self.green) <= 105.0
        )


def _label(mask: np.ndarray) -> tuple[np.ndarray, int]:
    if _ndimage is not None:
        return _ndimage.label(mask, structure=np.ones((3, 3), dtype=bool))
    return _label_fallback(mask)


def _label_fallback(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """Union-find labelling so the mod still works without scipy installed."""
    height, width = mask.shape
    labels = np.zeros((height, width), dtype=np.int32)
    parent: list[int] = [0]

    def find(node: int) -> int:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(first: int, second: int) -> None:
        first_root, second_root = find(first), find(second)
        if first_root != second_root:
            parent[max(first_root, second_root)] = min(first_root, second_root)

    rows, columns = np.nonzero(mask)
    next_label = 1
    for y, x in zip(rows.tolist(), columns.tolist()):
        neighbours = []
        for offset_y, offset_x in ((-1, -1), (-1, 0), (-1, 1), (0, -1)):
            neighbour_y, neighbour_x = y + offset_y, x + offset_x
            if 0 <= neighbour_y < height and 0 <= neighbour_x < width:
                value = labels[neighbour_y, neighbour_x]
                if value:
                    neighbours.append(int(value))
        if not neighbours:
            labels[y, x] = next_label
            parent.append(next_label)
            next_label += 1
        else:
            smallest = min(neighbours)
            labels[y, x] = smallest
            for other in neighbours:
                union(smallest, other)

    if next_label == 1:
        return labels, 0
    remap = {}
    for label in range(1, next_label):
        root = find(label)
        remap.setdefault(root, len(remap) + 1)
    lookup = np.zeros(next_label, dtype=np.int32)
    for label in range(1, next_label):
        lookup[label] = remap[find(label)]
    return lookup[labels], len(remap)


def _components(
    mask: np.ndarray,
    pixels: np.ndarray,
    minimum_edge: int,
    maximum_edge: int,
    minimum_pixels: int,
    aspect: tuple[float, float] = (0.45, 2.2),
    fill: float = 0.28,
) -> list[Blob]:
    if not mask.any():
        return []
    labels, count = _label(mask)
    if count == 0:
        return []
    blobs: list[Blob] = []
    if _ndimage is not None:
        slices = _ndimage.find_objects(labels)
    else:
        slices = []
        for label in range(1, count + 1):
            rows, columns = np.nonzero(labels == label)
            slices.append(
                (
                    slice(int(rows.min()), int(rows.max()) + 1),
                    slice(int(columns.min()), int(columns.max()) + 1),
                )
            )
    for index, bounds in enumerate(slices, start=1):
        if bounds is None:
            continue
        row_slice, column_slice = bounds
        height = row_slice.stop - row_slice.start
        width = column_slice.stop - column_slice.start
        if not (
            minimum_edge <= width <= maximum_edge
            and minimum_edge <= height <= maximum_edge
        ):
            continue
        patch = labels[bounds] == index
        area = int(patch.sum())
        if area < minimum_pixels:
            continue
        if not aspect[0] <= width / height <= aspect[1]:
            continue
        if area / (width * height) < fill:
            continue
        local_rows, local_columns = np.nonzero(patch)
        centered = np.column_stack((local_columns-local_columns.mean(),
                                    local_rows-local_rows.mean()))
        eigenvalues = np.linalg.eigvalsh(centered.T @ centered / area)
        elongation = float(eigenvalues[-1]/max(eigenvalues[0],0.1))
        colors = pixels[bounds][patch]
        blobs.append(
            Blob(
                x=float(column_slice.start + local_columns.mean()),
                y=float(row_slice.start + local_rows.mean()),
                width=int(width),
                height=int(height),
                pixels=area,
                red=float(colors[:, 0].mean()),
                green=float(colors[:, 1].mean()),
                blue=float(colors[:, 2].mean()),
                elongation=elongation,
            )
        )
    return blobs


def _as_array(image) -> np.ndarray:
    return np.asarray(image.convert("RGB"), dtype=np.int16)


def _scale_for(image) -> float:
    return max(0.45, min(image.width / 1330.0, image.height / 880.0))


# Terrain on the world map peaks around 87; markers measure 222-255.
MIN_MARKER_CHROMA = 120


def _marker_components(pixels, mask, scale) -> list[Blob]:
    return _components(
        mask,
        pixels,
        minimum_edge=max(2, round(3 * scale)),
        maximum_edge=max(8, round(18 * scale)),
        minimum_pixels=max(4, round(6 * scale * scale)),
    )


# A character on the map is drawn as a facing arrow, not a dot.  Android 20
# pointing south on Blue islands (2026-09-10, 1066x705) was a red triangle 15
# wide and 6 tall, over the 14-pixel edge cap and the 2.2 aspect cap that
# suit the compact event squares, so the frame held no marker, the objective
# never resolved, the tones stayed silent and T was refused.  Colour-specific
# masks admit near-pure primaries only, which terrain never is, so a looser
# shape there costs nothing; the broad saturation pass keeps the tight one.
SPRITE_ASPECT = (0.3, 3.5)


def _sprite_components(pixels, mask, scale) -> list[Blob]:
    return _components(
        mask,
        pixels,
        minimum_edge=max(2, round(3 * scale)),
        maximum_edge=max(8, round(20 * scale)),
        minimum_pixels=max(4, round(6 * scale * scale)),
        aspect=SPRITE_ASPECT,
    )


def find_map_markers(
    image,
    region: tuple[int, int, int, int] | None = None,
    *,
    pixels: np.ndarray | None = None,
) -> list[Blob]:
    """Find the compact HUD squares drawn over the world map.

    Colour-specific masks are tried first and only then a broad saturation
    pass.  This is not an optimization: the map artwork is itself saturated, so
    a single broad mask lets a marker merge into the landmass it sits on and
    the combined blob is then discarded for being too large.  A live capture
    with a clearly visible red objective square returned zero red markers that
    way.  Isolating each marker colour keeps the squares separate from terrain.
    """
    pixels = _as_array(image) if pixels is None else pixels
    if region is not None:
        left, top, right, bottom = region
        left = max(0, left)
        top = max(0, top)
        right = min(image.width, right)
        bottom = min(image.height, bottom)
        if right - left < 4 or bottom - top < 4:
            return []
        pixels = pixels[top:bottom, left:right]
        origin = (left, top)
    else:
        origin = (0, 0)

    red, green, blue = pixels[:, :, 0], pixels[:, :, 1], pixels[:, :, 2]
    brightest = pixels.max(axis=2)
    darkest = pixels.min(axis=2)
    scale = _scale_for(image)

    # Deliberately tighter than Blob.is_red / Blob.is_yellow.  These decide what
    # is allowed to touch what; classification of the result stays broader so a
    # dimmed or blended marker is still labelled correctly.
    # Map terrain contains a lot of orange-brown (e.g. 166,115,79) whose red
    # dominance is around 50.  The markers are near-pure primaries -- a live
    # capture measured the objective square at (255,0,0) -- so requiring a much
    # larger dominance keeps the square from merging into the landmass under it.
    red_mask = (red >= 110) & ((red - green) >= 90) & ((red - blue) >= 90)
    yellow_mask = (red >= 140) & (green >= 140) & (blue <= 90)

    blobs = _sprite_components(pixels, red_mask, scale)
    blobs += _sprite_components(pixels, yellow_mask, scale)

    if not blobs or region is not None:
        # Inside the minimap ROI it is safe to include the broad pass even when
        # red/yellow markers were found.  That is how differently-coloured
        # objectives remain visible alongside ordinary yellow events.  A
        # whole-window broad pass is still only a fallback because saturated
        # game art and emulator chrome otherwise produce dozens of candidates.
        saturated = (brightest >= 65) & ((brightest - darkest) >= 45)
        broad = _marker_components(pixels, saturated, scale)
        blobs = broad if not blobs else blobs + broad

    if origin != (0, 0):
        blobs = [
            Blob(
                blob.x + origin[0],
                blob.y + origin[1],
                blob.width,
                blob.height,
                blob.pixels,
                blob.red,
                blob.green,
                blob.blue,
                blob.elongation,
            )
            for blob in blobs
        ]

    # The masks can overlap on a blended edge; keep one blob per position.
    unique: list[Blob] = []
    for blob in sorted(blobs, key=lambda item: -item.pixels):
        if not any(
            math.hypot(blob.x - kept.x, blob.y - kept.y) <= 3.0 for kept in unique
        ):
            unique.append(blob)
    return unique


def story_markers(blobs: list[Blob]) -> list[Blob]:
    """Return map markers that the game documents as main story events.

    Dragon Adventure's manual calls them red circles; at the captured HUD
    scale they rasterize as compact red squares/dots with a dark outline.
    Yellow markers are deliberately excluded: player guides consistently use
    those for optional/free events rather than the route that advances story.
    """
    return [blob for blob in blobs if blob.is_red]


def _hue(blob: Blob) -> float:
    """Hue in degrees, 0-360, for grouping markers by colour."""
    red, green, blue = blob.red, blob.green, blob.blue
    brightest = max(red, green, blue)
    darkest = min(red, green, blue)
    chroma = brightest - darkest
    if chroma <= 0:
        return 0.0
    if brightest == red:
        angle = ((green - blue) / chroma) % 6.0
    elif brightest == green:
        angle = ((blue - red) / chroma) + 2.0
    else:
        angle = ((red - green) / chroma) + 4.0
    return angle * 60.0


def _hue_distance(first: float, second: float) -> float:
    difference = abs(first - second) % 360.0
    return min(difference, 360.0 - difference)


HUE_GROUP_TOLERANCE = 30.0


def group_markers_by_hue(blobs: list[Blob], tolerance: float = HUE_GROUP_TOLERANCE):
    """Cluster markers by colour without naming any colour."""
    groups: list[list[Blob]] = []
    for blob in sorted(blobs, key=_hue):
        hue = _hue(blob)
        for group in groups:
            if _hue_distance(hue, _hue(group[0])) <= tolerance:
                group.append(blob)
                break
        else:
            groups.append([blob])
    return groups


def distinct_marker(blobs: list[Blob]) -> Blob | None:
    """Return the odd-coloured marker among a set of map markers.

    A fallback for events the game does not draw red.  ``story_markers`` above
    encodes the documented red convention and is tried first; this rule needs no
    colour at all, identifying the highlighted destination as the single marker
    whose hue differs from the majority.  If there is no clear majority, or more
    than one marker stands out, no claim is made.
    """
    if len(blobs) < 2:
        return None
    groups = group_markers_by_hue(blobs)
    if len(groups) < 2:
        return None
    groups.sort(key=len)
    smallest, next_smallest = groups[0], groups[1]
    if len(smallest) != 1:
        return None
    if len(next_smallest) == 1:
        # Two singletons: nothing is the odd one out.
        return None
    return smallest[0]


def has_map_event_description(image, *, pixels: np.ndarray | None = None) -> bool:
    """Detect the upper-left description panel shown while over a map event.

    The panel is the game's secondary confirmation that a point of interest is
    active.  It consists of a yellow location/event label on a cloud banner in
    the upper-left playfield.  This deliberately detects the panel's visual
    presence, not its text, so it does not depend on a per-map OCR dictionary.
    It is only used together with live arrow/marker overlap, so neither a map
    coordinate nor a coordinate-table match is required.
    """
    pixels = _as_array(image) if pixels is None else pixels
    height, width = pixels.shape[:2]
    # Relative to the full captured game window.  The crop is broad enough for
    # the 4:3 playfield when PCSX2 is letterboxed or includes its title bar, but
    # excludes the map's yellow optional markers in the lower-left.
    top = int(height * 0.075)
    bottom = int(height * 0.22)
    left = int(width * 0.10)
    right = int(width * 0.48)
    patch = pixels[top:bottom, left:right]
    if patch.size == 0:
        return False
    red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    yellow = (
        (red >= 100)
        & (green >= 70)
        & (blue <= 100)
        & (red >= blue * 1.3)
        & (green >= blue * 1.1)
        & (red - green >= -30)
    )
    # The recorded Wasteland label provides several thousand matching pixels;
    # this low floor leaves room for short translated labels and scaling while
    # remaining far above the empty-panel frames in the corpus.
    return int(yellow.sum()) >= max(80, int(patch.shape[0] * patch.shape[1] * 0.003))


def find_white_blobs(
    image,
    region: tuple[int, int, int, int] | None = None,
    *,
    pixels: np.ndarray | None = None,
) -> list[Blob]:
    """Every near-white compact HUD element, arrow and text alike.

    ``region`` restricts the search.  Scanning the whole window returned 46
    candidates on a live capture -- including PCSX2's own title bar, menu and
    status text -- which is noise the arrow has to be found among.  The map
    panel holds about six.
    """
    pixels = _as_array(image) if pixels is None else pixels
    origin = (0, 0)
    if region is not None:
        left, top, right, bottom = (int(value) for value in region)
        left = max(0, left)
        top = max(0, top)
        right = min(image.width, right)
        bottom = min(image.height, bottom)
        if right - left < 8 or bottom - top < 8:
            return []
        pixels = pixels[top:bottom, left:right]
        origin = (left, top)
    darkest = pixels.min(axis=2)
    brightest = pixels.max(axis=2)
    mask = (darkest >= 150) & ((brightest - darkest) <= 40)
    scale = _scale_for(image)
    blobs = _components(
        mask,
        pixels,
        minimum_edge=max(3, round(4 * scale)),
        maximum_edge=max(12, round(24 * scale)),
        minimum_pixels=max(8, round(12 * scale * scale)),
        aspect=(0.35, 2.8),
        fill=0.25,
    )
    if origin == (0, 0):
        return blobs
    return [
        Blob(
            blob.x + origin[0],
            blob.y + origin[1],
            blob.width,
            blob.height,
            blob.pixels,
            blob.red,
            blob.green,
            blob.blue,
            blob.elongation,
        )
        for blob in blobs
    ]


def direct_player_arrow(blobs) -> Blob | None:
    """Identify the neutral-white arrow without waiting for player movement.

    The minimap's drifting clouds are blue-grey: their RGB channels differ by
    20 or more in the recorded frames.  The player arrow is neutral grey/white
    with equal channels.  A unique neutral candidate gives the guide an
    immediate anchor; temporal movement correlation remains the fallback for
    renderer or palette variants where this appearance test is ambiguous.
    """
    neutral = [
        blob
        for blob in blobs
        if min(blob.red, blob.green, blob.blue) >= 170.0
        and max(blob.red, blob.green, blob.blue)
        - min(blob.red, blob.green, blob.blue)
        <= 18.0
        # The direction arrow tapers. A filled white event dot or sparkle is
        # not a player, even when its colour is just as neutral as the arrow.
        and (blob.elongation >= 2.0
             or (max(blob.red,blob.green,blob.blue)-min(blob.red,blob.green,blob.blue)<=3
                 and blob.pixels/(blob.width*blob.height)<0.78)
             or (not blob.elongation and blob.pixels/(blob.width*blob.height)<0.80))
    ]
    return neutral[0] if len(neutral) == 1 else None


# Map markers are near-pure primaries; terrain and HUD text are much duller.
PANEL_MARKER_CHROMA = 150
# Absolute chroma alone is not enough.  The Zeni panel's text measured
# (237,162,72): chroma 165, which clears the threshold above, and a live run
# counted five of its glyphs as map markers.  Relative saturation separates them
# cleanly -- that text is 0.70 while the red marker (217,4,2) is 0.99 and the
# yellow (221,222,1) is 0.995.
MIN_MARKER_SATURATION = 0.90


def is_map_marker(blob: "Blob") -> bool:
    """Whether a blob is a marker drawn on the map rather than other HUD art."""
    brightest = max(blob.red, blob.green, blob.blue)
    darkest = min(blob.red, blob.green, blob.blue)
    if brightest <= 0:
        return False
    if (brightest - darkest) <= PANEL_MARKER_CHROMA:
        return False
    return (brightest - darkest) / brightest >= MIN_MARKER_SATURATION


# The minimap is a HUD component, so its location is stable even though its
# landmass, markers, and scale vary from map to map.  These deliberately broad
# full-window fractions contain the lower-left minimap in the recorded normal,
# maximized, bright, and dim captures while excluding the Zeni panel, emulator
# menu/status bars, and the upper-left event description.
MINIMAP_LEFT = 0.10
MINIMAP_TOP = 0.50
MINIMAP_RIGHT = 0.47
MINIMAP_BOTTOM = 0.96


def game_viewport(image) -> tuple[int, int, int, int] | None:
    """Find the rendered playfield, excluding emulator chrome and black bars.

    Use broad runs of coloured game pixels, independent of map artwork and
    marker count. A blank/faded capture cannot establish a viewport.
    """
    pixels = _as_array(image)[::2, ::2]
    coloured = (pixels.max(2) - pixels.min(2) >= 18) & (pixels.max(2) >= 35)
    rows = np.flatnonzero(coloured.mean(1) > 0.18)
    if len(rows) < image.height * 0.20:
        return None
    # Ignore small separate HUD/chrome runs above or below the playfield.
    runs = np.split(rows, np.flatnonzero(np.diff(rows) > 1) + 1)
    run = max(runs, key=len)
    if len(run) < image.height * 0.20:
        return None
    columns = np.flatnonzero(coloured[run[0]:run[-1]+1].mean(0) > 0.20)
    if len(columns) < image.width * 0.25:
        return None
    left, right = int(columns[0]*2), min(image.width, int(columns[-1]*2+2))
    top, bottom = int(rows[0]*2), min(image.height, int(rows[-1]*2+2))
    # Pillar bars expose the full render height even when dark terrain or a
    # pause overlay contains no chromatic pixels near the bottom of the game.
    if left >= 6 and right+6 < image.width:
        full = _as_array(image)
        bars = ((full[:, left-5].max(1) <= 12)
                & (full[:, right+5].max(1) <= 12))
        indices = np.flatnonzero(bars)
        if len(indices):
            spans = np.split(indices, np.flatnonzero(np.diff(indices)>1)+1)
            span = max(spans, key=len)
            if len(span) > image.height*0.5:
                top, bottom = int(span[0]), int(span[-1]+1)
    return left, top, right, bottom


def minimap_region(image) -> tuple[int, int, int, int]:
    """Return the map-agnostic lower-left HUD region.

    This region is intentionally independent of marker count.  The previous
    region grew outward from two coloured markers, so it could not exist when
    only one destination was available, while a marker was occluded by the
    arrow, or while the pause dimming reduced saturation.
    """
    viewport = game_viewport(image)
    if viewport is not None:
        left, top, right, bottom = viewport
        width, height = right-left, bottom-top
        # The HUD canvas is fixed in the rendered game, not in PCSX2's outer
        # window. Includes arrows beyond the landmass, excludes the character
        # standing beside the map. Neither terrain nor event positions set it.
        return (round(left+width*0.06), round(top+height*0.58),
                round(left+width*0.42), round(top+height*0.96))
    return (
        int(image.width * MINIMAP_LEFT),
        int(image.height * MINIMAP_TOP),
        int(image.width * MINIMAP_RIGHT),
        int(image.height * MINIMAP_BOTTOM),
    )


def is_minimap_marker(blob: "Blob") -> bool:
    """A coloured compact element after it has already been cropped to the map.

    Dimming in captured world-map frames reduced valid marker chroma below the
    whole-window threshold.  Within the minimap ROI a lower adaptive floor is
    safe because unrelated HUD text has already been excluded.
    """
    brightest = max(blob.red, blob.green, blob.blue)
    darkest = min(blob.red, blob.green, blob.blue)
    if brightest < 55.0:
        return False
    chroma = brightest - darkest
    return chroma >= 35.0 and chroma / brightest >= 0.55


def has_marker_outline(pixels: np.ndarray, blob: Blob, scale: float) -> bool:
    """Verify an enclosed HUD dot using its own local brightness scale.

    A compact saturated patch can also be clothing or unfamiliar terrain.
    Event dots have a dark border on *all four sides*. Search across the
    antialiased edge instead of assuming a map palette, a fixed border RGB,
    or a stored template. Relative contrast survives scene/pause dimming.
    Broad candidate discovery remains separate from this structural check.
    """
    x, y = round(blob.x), round(blob.y)
    height, width = pixels.shape[:2]
    margin = max(2, round(3 * scale))
    reach = max(blob.width, blob.height) // 2 + margin + 2
    if x < reach or y < reach or x + reach >= width or y + reach >= height:
        return False  # A clipped border is insufficient evidence.
    patch = pixels[y-reach:y+reach+1, x-reach:x+reach+1].max(axis=2)
    center = reach
    core = float(patch[center-1:center+2, center-1:center+2].max())
    if core <= 0:
        return False
    half_strip = max(1, round(scale))
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        radius = (blob.width if dx else blob.height) / 2
        border = []
        for distance in range(max(1, round(radius)-1), round(radius)+margin+1):
            samples = [
                patch[center + dy*distance + dx*t,
                      center + dx*distance + dy*t]
                for t in range(-half_strip, half_strip+1)
            ]
            border.append(float(np.mean(samples)))
        if min(border) > core * 0.60:
            return False
    return True


def has_marker_core(pixels: np.ndarray, blob: Blob) -> bool:
    """Separate flat, vivid event ink from shaded islands behind the HUD.

    Sample the core, not blended outline pixels. Shared event sprite colours
    use channels near either end of their own colour range; terrain has
    intermediate channels. This also accepts dim yellow, cyan and magenta.
    """
    x, y = round(blob.x), round(blob.y)
    core = pixels[max(0,y-1):y+2, max(0,x-1):x+2].astype(float)
    ordered = np.sort(core, axis=2)
    low, middle, high = (ordered[:,:,i] for i in range(3))
    chroma = high-low
    vivid = chroma / np.maximum(high, 1) >= 0.75
    flat = np.minimum(middle-low, high-middle) <= np.maximum(chroma, 1)*0.15
    return float((vivid & flat).mean()) >= 0.55


@dataclass(frozen=True)
class FrameAnalysis:
    """Everything the guide needs from one captured frame.

    The RGB conversion and expensive connected-component passes happen once.
    Consumers share these immutable observations instead of independently
    rescanning the same bitmap three or four times.
    """

    image: object
    region: tuple[int, int, int, int]
    markers: tuple[Blob, ...]
    white_blobs: tuple[Blob, ...]
    event_description: bool
    dragon_adventure_hud: bool

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    @property
    def world_map_visible(self) -> bool:
        """Whether this frame contains usable world-map navigation evidence."""
        # At contact the arrow can cover the only objective marker; the event
        # description is then stronger evidence than the missing marker.
        return self.dragon_adventure_hud and bool(self.white_blobs) and (
            bool(self.markers) or self.event_description
        )


def analyze_frame(image) -> FrameAnalysis:
    """Analyze one PCSX2 frame once, with the minimap as the source of truth."""
    region = minimap_region(image)
    adventure_hud = has_dragon_adventure_hud(image)
    if not adventure_hud:
        # Battles, loading and dialogue can all contain compact red/white
        # artwork in the old minimap crop. Do not even scan destinations until
        # the independent Dragon Adventure panel is present.
        return FrameAnalysis(image, region, (), (), False, False)
    pixels = _as_array(image)
    markers = tuple(
        blob
        for blob in find_map_markers(image, region, pixels=pixels)
        if is_minimap_marker(blob)
        and has_marker_outline(pixels, blob, _scale_for(image))
        and has_marker_core(pixels, blob)
    )
    whites = tuple(find_white_blobs(image, region, pixels=pixels))
    return FrameAnalysis(
        image=image,
        region=region,
        markers=markers,
        white_blobs=whites,
        event_description=has_map_event_description(image, pixels=pixels),
        dragon_adventure_hud=adventure_hud,
    )


# How far past the marker bounding box the minimap is assumed to extend.  The
# markers are map locations, so their spread approximates the landmass, but the
# arrow can sit outside them.
PANEL_EXPANSION = 0.75
PANEL_MARGIN = 40


# Markers on the minimap sit within a few hundred pixels of each other, while
# strongly coloured HUD text is far away.  Bounding *all* chromatic blobs was
# circular -- the panel was derived from the very blobs it was meant to filter,
# so one coloured glyph on the far side of the screen stretched the "panel"
# across the whole frame.  A live profile accumulated twenty marker positions
# that way, including a column of HUD entries at x = 1132 and pairs at y = 220,
# which is noise the map solver can never fit.
MARKER_CLUSTER_RADIUS = 260.0


def _densest_cluster(blobs: list[Blob]) -> list[Blob]:
    """The largest group of blobs that are near one another."""
    best: list[Blob] = []
    for anchor in blobs:
        near = [
            blob
            for blob in blobs
            if math.hypot(blob.x - anchor.x, blob.y - anchor.y)
            <= MARKER_CLUSTER_RADIUS
        ]
        if len(near) > len(best):
            best = near
    return best


def map_panel_region(image, blobs: list[Blob]) -> tuple[int, int, int, int] | None:
    """Bound the minimap from the markers drawn on it.

    Used to keep the arrow search off the rest of the screen without knowing
    where the game draws its minimap.  Returns ``None`` when too few markers are
    visible to bound anything, in which case callers should search everywhere
    rather than guess.
    """
    strong = [blob for blob in blobs if is_map_marker(blob)]
    if len(strong) < 2:
        return None
    strong = _densest_cluster(strong)
    if len(strong) < 2:
        return None
    left = min(blob.x for blob in strong)
    right = max(blob.x for blob in strong)
    top = min(blob.y for blob in strong)
    bottom = max(blob.y for blob in strong)
    pad_x = (right - left) * PANEL_EXPANSION + PANEL_MARGIN
    pad_y = (bottom - top) * PANEL_EXPANSION + PANEL_MARGIN
    return (
        int(left - pad_x),
        int(top - pad_y),
        int(right + pad_x) + 1,
        int(bottom + pad_y) + 1,
    )


def find_moving_arrow(
    current: list[Blob],
    previous: list[Blob],
    tolerance: float = 2.5,
) -> Blob | None:
    """Identify the arrow as the white element that moved while the map did not.

    This is the bootstrap: before any projection exists there is no way to
    predict where the arrow should be, and it is not reliably the largest white
    thing on screen.  But the HUD map is static, so between two frames in which
    the player moved, the arrow is the white blob that is not where a white
    blob was before.  Location markers never move, and HUD text does not drift.
    """
    if not current or not previous:
        return None

    def stationary(blob: Blob) -> bool:
        return any(
            math.hypot(blob.x - other.x, blob.y - other.y) <= tolerance
            for other in previous
        )

    moved = [blob for blob in current if not stationary(blob)]
    if not moved:
        return None
    # Size is not a reliable discriminator: on real captures an unrelated HUD
    # element that appeared between frames measured larger than the arrow.
    # Nominate only when the answer is unambiguous, and otherwise decline --
    # during play the next frame pair is milliseconds away, and a wrong
    # nomination poisons the calibration it feeds.
    moved.sort(key=lambda blob: -blob.pixels)
    if len(moved) > 1 and moved[1].pixels >= moved[0].pixels * 0.4:
        return None
    return moved[0]


def find_player_arrow(
    image,
    predicted: tuple[float, float] | None = None,
    search_radius: float = 1.0,
) -> Blob | None:
    """Locate the white player arrow drawn on the Dragon Adventure world map.

    The arrow is the mod's calibration ground truth: unlike location markers it
    is always drawn, on every map, no matter what the player has unlocked.
    ``predicted`` and ``search_radius`` are normalized to the window and only
    narrow the search once a projection already exists.
    """
    pixels = _as_array(image)
    darkest = pixels.min(axis=2)
    brightest = pixels.max(axis=2)
    # Near-white and bright: the arrow is desaturated against a coloured map.
    mask = (darkest >= 150) & ((brightest - darkest) <= 40)

    if predicted is not None and search_radius < 1.0:
        radius_pixels = search_radius * max(image.width, image.height)
        center_x = predicted[0] * image.width
        center_y = predicted[1] * image.height
        grid_y, grid_x = np.ogrid[: image.height, : image.width]
        within = (grid_x - center_x) ** 2 + (grid_y - center_y) ** 2 <= radius_pixels**2
        mask = mask & within

    scale = _scale_for(image)
    blobs = _components(
        mask,
        pixels,
        minimum_edge=max(3, round(4 * scale)),
        maximum_edge=max(12, round(24 * scale)),
        minimum_pixels=max(8, round(12 * scale * scale)),
        aspect=(0.35, 2.8),
        fill=0.25,
    )
    if not blobs:
        return None
    if predicted is None:
        # Without a prior the arrow is not separable from other white HUD text,
        # so require a single dominant candidate rather than guessing.
        blobs.sort(key=lambda blob: -blob.pixels)
        if len(blobs) > 1 and blobs[1].pixels > blobs[0].pixels * 0.65:
            return None
        return blobs[0]
    center_x = predicted[0] * image.width
    center_y = predicted[1] * image.height
    return min(
        blobs,
        key=lambda blob: math.hypot(blob.x - center_x, blob.y - center_y),
    )


def has_dragon_adventure_hud(image, *, pixels: np.ndarray | None = None) -> bool:
    """Recognize the gold-bordered purple Zeni panel in navigation scenes.

    The spatial arrangement matters: unrelated purple and gold pixels during
    a fight must not open navigation. Relative colour contrasts also survive
    the emulator's pause dimming. This cheap, subsampled crop is evaluated
    before any marker or arrow connected-component scans.
    """
    height, width = image.height, image.width
    left = int(width * 0.53)
    right = int(width * 0.94)
    top = int(height * 0.08)
    bottom = int(height * 0.25)
    if pixels is None:
        patch = _as_array(image.crop((left, top, right, bottom)))[::2, ::2]
    else:
        patch = pixels[top:bottom:2, left:right:2]
    if patch.size == 0:
        return False
    red, green, blue = patch[:, :, 0], patch[:, :, 1], patch[:, :, 2]
    purple = (
        (blue >= 20)
        & ((blue - red) >= 12)
        & ((blue - green) >= 12)
        & (green <= blue * 0.72)
    )
    gold = (red >= 55) & (green >= 35) & (blue <= np.minimum(red, green) * 0.70)
    above = np.zeros_like(gold)
    below = np.zeros_like(gold)
    depth = max(2, round(height * 0.07 / 2))
    for offset in range(1, min(depth + 1, len(gold))):
        above[offset:] |= gold[:-offset]
        below[:-offset] |= gold[offset:]
    bordered_width = (purple & above & below).sum(axis=1)
    wide_rows = bordered_width >= width * 0.07 / 2
    return bool(wide_rows.sum() >= max(2, height * 0.008 / 2))


# --- Window capture ---------------------------------------------------------


_ENUM_WINDOWS_PROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)
)
_cached_window_handle: int | None = None


def find_game_windows() -> list[int]:
    from .windows import game_windows
    return game_windows()


def _game_window_handle():
    """Return the PCSX2 game window handle and bounds, without requiring focus."""
    global _cached_window_handle

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    handle = _cached_window_handle
    if handle is None or not user32.IsWindow(handle):
        matches = find_game_windows()
        if len(matches) != 1:
            _cached_window_handle = None
            raise ObjectiveNotReady(
                f"Expected one PCSX2 game window, found {len(matches)}"
            )
        handle = matches[0]
        _cached_window_handle = handle

    try:
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass
    if user32.IsIconic(handle):
        raise ObjectiveNotReady("PCSX2 is minimized, so its window has no content")
    rectangle = wintypes.RECT()
    if not user32.GetWindowRect(handle, ctypes.byref(rectangle)):
        _cached_window_handle = None
        raise ObjectiveNotReady("PCSX2's window bounds could not be read")
    bounds = (rectangle.left, rectangle.top, rectangle.right, rectangle.bottom)
    if bounds[2] - bounds[0] < 320 or bounds[3] - bounds[1] < 240:
        raise ObjectiveNotReady("PCSX2's game window is too small to read the map")
    return handle, bounds


# PrintWindow with this flag renders the window's own surface, including
# hardware-composited content, instead of copying whatever pixels happen to be
# on screen.  Plain PW_DEFAULT (0) returns a mostly black frame for PCSX2.
PW_RENDERFULLCONTENT = 0x00000002
# Below this fraction of non-black pixels the capture did not really render.
MIN_RENDERED_FRACTION = 0.25


def _print_window(handle, bounds):
    """Copy a window's own pixels, even when it is behind another window."""
    import win32gui
    import win32ui
    from PIL import Image

    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    window_dc = win32gui.GetWindowDC(handle)
    source = target = bitmap = None
    try:
        source = win32ui.CreateDCFromHandle(window_dc)
        target = source.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(source, width, height)
        target.SelectObject(bitmap)
        ok = ctypes.windll.user32.PrintWindow(
            handle, target.GetSafeHdc(), PW_RENDERFULLCONTENT
        )
        if not ok:
            return None
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1
        )
    finally:
        if bitmap is not None:
            win32gui.DeleteObject(bitmap.GetHandle())
        if target is not None:
            target.DeleteDC()
        if source is not None:
            source.DeleteDC()
        win32gui.ReleaseDC(handle, window_dc)


def _looks_rendered(image) -> bool:
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    return float((pixels.max(axis=2) > 12).mean()) >= MIN_RENDERED_FRACTION


def capture_game_window():
    """Capture the PCSX2 game window without needing it focused.

    An earlier revision grabbed the screen region the window occupies, which
    forced PCSX2 to be the foreground window -- otherwise it would have copied
    whatever was on top.  That made the HUD unreadable during ordinary use (a
    console, a screen reader, or any other focused window was enough), and
    since the player arrow is the calibration anchor, it silently prevented
    maps from ever calibrating.  PrintWindow reads the window's own surface, so
    focus and occlusion no longer matter.
    """
    if sys.platform != "win32":
        raise ObjectiveNotReady("Window capture is only implemented on Windows")
    handle, bounds = _game_window_handle()

    try:
        image = _print_window(handle, bounds)
    except (ImportError, OSError, RuntimeError) as error:
        image = None
        reason = f"{type(error).__name__}: {error}"
    else:
        reason = "PrintWindow returned an unrendered frame"
    if image is not None and _looks_rendered(image):
        return image

    # Fall back to a screen grab, which does need the window to be visible and
    # unobstructed, rather than giving up on reading the HUD entirely.
    try:
        from PIL import ImageGrab
    except ImportError as error:
        raise ObjectiveNotReady(
            "Pillow is required for live story-marker discovery"
        ) from error
    grabbed = ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")
    if not _looks_rendered(grabbed):
        raise ObjectiveNotReady(
            f"PCSX2's window could not be captured ({reason}) and the screen "
            "grab was blank; is the window obscured or minimized?"
        )
    return grabbed



# --- Blob tracking ----------------------------------------------------------
# Identifying the player arrow by size or by "the one thing that moved" both
# fail on the world map: a live capture measured four drifting cloud blobs
# around the arrow, one of them larger than it (n=55 against the arrow's n=40).
# Tracks let the arrow be identified by *behaviour* instead -- it is the only
# white element whose motion is driven by player input.

# The arrow moves far between samples -- 400 world units is about 22 px at the
# captured HUD scale, and the guide samples roughly every 0.4 s -- so a tight
# radius hands it a new identity on every move and no track ever accumulates
# enough movement to solve.  The radius is generous; the one-to-one greedy
# assignment below, closest pairs first, is what stops neighbouring blobs from
# swapping identities.
TRACK_MATCH_RADIUS = 60.0
TRACK_MAX_MISSES = 3


@dataclass
class Track:
    """One white HUD element followed across frames."""

    identifier: int
    x: float
    y: float
    pixels: int
    misses: int = 0
    seen: int = 1

    def update(self, blob: "Blob") -> None:
        self.x = blob.x
        self.y = blob.y
        self.pixels = blob.pixels
        self.misses = 0
        self.seen += 1


class BlobTracker:
    """Associates white blobs across frames by nearest neighbour."""

    def __init__(self, match_radius: float = TRACK_MATCH_RADIUS):
        self.match_radius = match_radius
        self.tracks: dict[int, Track] = {}
        self._next_id = 1

    def update(self, blobs: list[Blob]) -> dict[int, Blob]:
        """Advance every track; return {track id: blob seen this frame}."""
        unclaimed = list(blobs)
        seen: dict[int, Blob] = {}

        # Greedy nearest-neighbour, closest pairs first, so two tracks cannot
        # both claim the same blob.
        pairs = []
        for identifier, track in self.tracks.items():
            for index, blob in enumerate(unclaimed):
                distance = math.hypot(blob.x - track.x, blob.y - track.y)
                if distance <= self.match_radius:
                    pairs.append((distance, identifier, index))
        pairs.sort()
        claimed_tracks: set[int] = set()
        claimed_blobs: set[int] = set()
        for _distance, identifier, index in pairs:
            if identifier in claimed_tracks or index in claimed_blobs:
                continue
            claimed_tracks.add(identifier)
            claimed_blobs.add(index)
            blob = unclaimed[index]
            self.tracks[identifier].update(blob)
            seen[identifier] = blob

        for identifier, track in list(self.tracks.items()):
            if identifier in claimed_tracks:
                continue
            track.misses += 1
            if track.misses > TRACK_MAX_MISSES:
                del self.tracks[identifier]

        for index, blob in enumerate(unclaimed):
            if index in claimed_blobs:
                continue
            identifier = self._next_id
            self._next_id += 1
            self.tracks[identifier] = Track(identifier, blob.x, blob.y, blob.pixels)
            seen[identifier] = blob

        return seen

    def reset(self) -> None:
        self.tracks.clear()
