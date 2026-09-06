"""Solve a map's projection from the player arrow.

The minimap draws the player as a small white arrow.  That is worth more than
every marker put together, because it is a *known* correspondence: the arrow's
screen position and the player's world position are the same thing, so the
projection can be fitted directly instead of guessed at.

Matching markers to table entries was the previous approach and it never
worked.  Four markers against six points leaves 360 assignments whose best fits
sit within 1.13x of each other, and accumulating more markers only helps if the
extra ones are real -- a live profile had collected twenty positions of which
sixteen were HUD text and panel-animation duplicates.  None of that ambiguity
exists here: fly for a few seconds and every sample is another equation.

The minimap is a fixed, unrotating, top-down view -- confirmed by markers
holding identical screen positions while the player moved 1600 world units --
so the projection is axis-aligned:

    px = a * x + c        py = b * z + d

East is +X and North is +Z, and screen y grows downward, so ``a`` is positive
and ``b`` negative.  Four parameters over many samples is heavily
overdetermined, which is what makes the result trustworthy.
"""

from __future__ import annotations

import math

# How far a blob may move between frames and still be the same one.  The arrow
# crosses the panel slowly; this is loose enough for a dropped frame and tight
# enough not to swallow a nearby static marker.
TRACK_RADIUS_PX = 60.0
# Enough samples that a fit means something.  Six was tried and is too few:
# a live solve at exactly six samples over 264 world units produced an axis
# scale ratio of 0.697 where a top-down map should be near 1.0, and only two of
# four markers landed within tolerance of a table point.  The residual was small
# the whole time, because a short baseline fits its own few points nicely and
# then extrapolates badly across the rest of the map.
MIN_SAMPLES = 12
# The player must actually go somewhere, or every candidate fits equally well.
MIN_WORLD_TRAVEL = 900.0
# Travel alone can be a long run along one axis, which leaves the other axis
# estimated from almost no spread.  Both have to be exercised.
MIN_AXIS_SPAN = 400.0
MAX_RESIDUAL_PX = 6.0
# A static marker fits px = 0 * x + c perfectly, so a flat fit has to be
# rejected explicitly -- the scale bounds below are what do it.
MIN_SCALE = 0.005
MAX_SCALE = 1.0
# The minimap is not stretched, so the two axes share a scale within reason.
MIN_AXIS_RATIO = 0.5
MAX_AXIS_RATIO = 2.0
# The arrow cannot leave the panel, so once the player flies past the edge of
# the map it stops moving while the world position keeps changing.  A live
# session covered 6878 world units north-south on a map only 2882 units deep,
# so a good share of those samples were pinned against the edge -- and a pinned
# sample is a false correspondence that drags the slope toward zero.  Blobs
# this close to the panel border are therefore not recorded.
PANEL_EDGE_MARGIN_PX = 10.0


def _fit_line(inputs, outputs):
    count = len(inputs)
    if count < 2:
        return None
    mean_in = sum(inputs) / count
    mean_out = sum(outputs) / count
    spread = sum((value - mean_in) ** 2 for value in inputs)
    if spread < 1e-9:
        return None
    slope = sum(
        (inputs[i] - mean_in) * (outputs[i] - mean_out) for i in range(count)
    ) / spread
    return slope, mean_out - slope * mean_in


class ArrowSolver:
    """Accumulates white-blob tracks and fits the projection to the arrow."""

    def __init__(self) -> None:
        self._tracks: list[dict] = []

    @property
    def sample_count(self) -> int:
        return max((len(track["observations"]) for track in self._tracks), default=0)

    @property
    def spans(self) -> tuple[float, float]:
        """Widest world extent covered on each axis, for progress reporting."""
        best = (0.0, 0.0)
        for track in self._tracks:
            observations = track["observations"]
            if len(observations) < 2:
                continue
            xs = [o[0][0] for o in observations]
            zs = [o[0][2] for o in observations]
            best = max(best, (max(xs) - min(xs), max(zs) - min(zs)))
        return best

    @property
    def travel(self) -> float:
        return max(
            (self._travel(track["observations"]) for track in self._tracks),
            default=0.0,
        )

    @staticmethod
    def _travel(observations) -> float:
        return sum(
            math.hypot(
                observations[i][0][0] - observations[i - 1][0][0],
                observations[i][0][2] - observations[i - 1][0][2],
            )
            for i in range(1, len(observations))
        )

    def observe(self, player, blobs, region=None) -> None:
        """Record one frame: where the player is, and every white blob drawn.

        ``region`` is the minimap panel.  When given, blobs pinned against its
        border are ignored, because an arrow that has run out of panel is no
        longer reporting where the player is.
        """
        if region is not None:
            left, top, right, bottom = region
            blobs = [
                blob
                for blob in blobs
                if left + PANEL_EDGE_MARGIN_PX <= blob.x <= right - PANEL_EDGE_MARGIN_PX
                and top + PANEL_EDGE_MARGIN_PX <= blob.y <= bottom - PANEL_EDGE_MARGIN_PX
            ]
        claimed: set[int] = set()
        for blob in blobs:
            chosen, best = None, None
            for index, track in enumerate(self._tracks):
                if index in claimed:
                    continue
                last = track["last"]
                distance = math.hypot(last[0] - blob.x, last[1] - blob.y)
                if best is None or distance < best:
                    chosen, best = index, distance
            if chosen is not None and best is not None and best <= TRACK_RADIUS_PX:
                self._tracks[chosen]["observations"].append(
                    (player, blob.x, blob.y)
                )
                self._tracks[chosen]["last"] = (blob.x, blob.y)
                claimed.add(chosen)
            else:
                self._tracks.append(
                    {"last": (blob.x, blob.y),
                     "observations": [(player, blob.x, blob.y)]}
                )

    def solve(self):
        """Return a six-term affine for the arrow's track, or None.

        The coefficients are laid out so ``navigation.project_with`` can apply
        them unchanged; the two cross terms are zero because the map does not
        rotate.
        """
        best = None
        for track in self._tracks:
            observations = track["observations"]
            if len(observations) < MIN_SAMPLES:
                continue
            if self._travel(observations) < MIN_WORLD_TRAVEL:
                continue
            xs = [o[0][0] for o in observations]
            zs = [o[0][2] for o in observations]
            if max(xs) - min(xs) < MIN_AXIS_SPAN:
                continue
            if max(zs) - min(zs) < MIN_AXIS_SPAN:
                continue
            horizontal = _fit_line(
                [o[0][0] for o in observations], [o[1] for o in observations]
            )
            vertical = _fit_line(
                [o[0][2] for o in observations], [o[2] for o in observations]
            )
            if horizontal is None or vertical is None:
                continue
            a, c = horizontal
            b, d = vertical
            if a <= 0.0 or b >= 0.0:
                continue
            if not (MIN_SCALE <= abs(a) <= MAX_SCALE):
                continue
            if not (MIN_SCALE <= abs(b) <= MAX_SCALE):
                continue
            ratio = abs(a / b)
            if not (MIN_AXIS_RATIO <= ratio <= MAX_AXIS_RATIO):
                continue
            residual = max(
                math.hypot(a * o[0][0] + c - o[1], b * o[0][2] + d - o[2])
                for o in observations
            )
            if residual > MAX_RESIDUAL_PX:
                continue
            if best is None or residual < best[0]:
                best = (residual, [a, 0.0, c, 0.0, b, d], len(observations))
        if best is None:
            return None
        return best[1], best[0], best[2]
