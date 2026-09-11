"""Offline checks for the minimap reader, against captured frames.

No emulator, no game, no player.  Each fixture under ``reference/vision`` is
one real capture of the PCSX2 window with what the reader must see in it
written down here beside it.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PIL import Image

from bt2 import vision

FIXTURES = Path(__file__).resolve().parents[2] / "reference" / "vision"
CHECKS = []


def check(function):
    CHECKS.append(function)
    return function


def frame(name: str):
    return Image.open(FIXTURES / name).convert("RGB")


@check
def test_a_character_arrow_facing_south_is_a_story_marker():
    """Android 20 on Blue islands, 2026-09-10, standing still and facing south.

    His marker is a red triangle 15 wide and 6 tall at 1066x705 -- wider than
    the event squares the finder was shaped for -- and the guide spent three
    sessions without an objective, tones or T because it was discarded on
    size before any colour check.  The whole frame must read as a world map.
    """
    analysis = vision.analyze_frame(frame("gero_south.png"))
    assert analysis.dragon_adventure_hud
    reds = [blob for blob in analysis.markers if blob.is_red]
    assert len(reds) == 1, [(blob.x, blob.y) for blob in analysis.markers]
    marker = reds[0]
    assert abs(marker.x - 356) <= 2 and abs(marker.y - 514) <= 2, (marker.x, marker.y)
    assert marker.width >= 14 and marker.height <= 7, (marker.width, marker.height)
    assert analysis.world_map_visible


@check
def test_the_looser_shape_admits_nothing_else_on_that_frame():
    """Terrain and coastline must still fail: the colour masks do the work."""
    analysis = vision.analyze_frame(frame("gero_south.png"))
    assert len(analysis.markers) == 1, [
        (blob.x, blob.y, blob.red, blob.green, blob.blue) for blob in analysis.markers
    ]


def main() -> int:
    if not FIXTURES.is_dir() or not any(FIXTURES.glob("*.png")):
        # Captures of the running game are never committed (see .gitignore),
        # so a fresh clone has none.  Say so rather than fail or pass quietly.
        print(f"skipped: no captures under {FIXTURES}")
        return 0
    failures = []
    for function in CHECKS:
        try:
            function()
        except Exception:
            failures.append(function.__name__)
            print(f"FAIL {function.__name__}:")
            traceback.print_exc()
        else:
            print(f"  ok   {function.__name__}")
    print(f"{len(CHECKS) - len(failures)}/{len(CHECKS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
