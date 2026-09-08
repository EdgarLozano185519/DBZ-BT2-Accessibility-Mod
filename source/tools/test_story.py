"""Offline tests for the story reader, against real captures and fake RAM.

No emulator, no player.  The captures in `reference/probe` are real EE RAM with
a screenshot beside each one, so what the reader *should* say on them is known
independently of the reader.  Everything else is synthetic, which is the only
way to test the cases that matter most: refusing a read rather than speaking
something wrong.

    python test_story.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from bt2 import story

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "reference" / "probe"
CAPTURE_BASE = 0x00100000


class CapturePine:
    """Serves reads out of a capture file, like PINE would from the game."""

    def __init__(self, data: bytes, base: int = CAPTURE_BASE):
        self.data = data
        self.base = base

    def _slice(self, address: int, size: int) -> bytes:
        offset = address - self.base
        if offset < 0 or offset + size > len(self.data):
            raise ValueError(f"0x{address:08X} is outside this capture")
        return self.data[offset:offset + size]

    def read32(self, address: int) -> int:
        return struct.unpack("<I", self._slice(address, 4))[0]

    def read_aligned_range(self, address: int, size: int, allow_large=False):
        return self._slice(address, size)


# A synthetic RAM block wide enough to hold both the display pointer and the
# scene text buffer, without carrying the 17 MB that spanning them from the
# base of EE RAM would cost on every call.
FAKE_BASE = 0x008C0000
FAKE_SIZE = 0x00800000
# Inside the scene text buffer: what a cutscene box looks like.
SCENE_TARGET = 0x0109F400
# In a menu's own allocation, near where the real ones sit: what an option's
# flavour text looks like. Read by F12, never spoken by itself.
MENU_TARGET = 0x00CA9F40


def fake_ram(text: str, pointer: int = story.DISPLAY_POINTER,
             target: int = SCENE_TARGET, base: int = FAKE_BASE,
             size: int = FAKE_SIZE, bom: bytes = story.BOM) -> CapturePine:
    """A block of zeros with one string in it and a pointer at it.

    The string lands in the scene text buffer by default, because that is
    where a cutscene box lives and the reader now speaks nothing else.  Pass
    `target=MENU_TARGET` for a line drawn by a menu instead.
    """
    data = bytearray(size)
    data[pointer - base:pointer - base + 4] = struct.pack("<I", target)
    blob = bom + text.encode("utf-16-le") + b"\x00\x00"
    data[target - base:target - base + len(blob)] = blob
    return CapturePine(bytes(data), base)


class Recorder:
    def __init__(self):
        self.said: list[str] = []

    def say(self, text, **_):
        self.said.append(text)


CHECKS: list[tuple[str, bool]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append((name, passed))
    mark = "ok  " if passed else "FAIL"
    print(f"  {mark} {name}" + (f"  -- {detail}" if detail and not passed else ""))


# Cutscene boxes, whose text the game loaded into the scene buffer.
SCENES = {
    "cut0": "I guess your little pet monsters weren't as strong as you thought.",
    "cut1": "Heh heh heh... You're getting a bit ahead of yourself, don't you think?",
    "cut2": "Kyeh!",
    "cut5": "It seemed to be an easy victory for the Z fighters, but...",
    "cut6": "...?!",
}

# Prose a menu was drawing. F12 reads all of it; the reader speaks none of it.
MENUS = {
    "auto0": "You can set options during the game. What should I do...?",
    "diff0": ("Set the Match level to your strength. "
              "You can always adjust it later!"),
    "library": ("You can read everyone's profile. "
                "We can study together if you want!"),
    "events0": "What's wrong? Have you lost your nerve?",
}


def test_captures() -> None:
    """What the reader says on real RAM, against the screenshots taken with it."""
    print("\nReal captures (expected text read off the screenshots):")
    for name, want in SCENES.items():
        path = PROBE / f"{name}.bin"
        if not path.is_file():
            check(f"{name} present", False, "capture missing")
            continue
        pine = CapturePine(path.read_bytes())
        # Read twice: the reader requires a value to settle before speaking.
        reader = story.StoryReader(Recorder())
        reader.poll(pine)
        got = reader.poll(pine)
        check(f"{name} is a scene box and is spoken", got == want, f"got {got!r}")

    # The title screen draws no prose and the pointer aims at bytes that are
    # not text. Silence is the only correct answer.
    path = PROBE / "pos0.bin"
    if path.is_file():
        pine = CapturePine(path.read_bytes())
        check("pos0 (title) is refused", story.read_displayed(pine) is None)


def test_menus_are_never_narrated() -> None:
    """A menu's prose is F12's to read and no business of the narrator.

    The player asked for this in as many words after hearing every option's
    flavour text announced as they browsed: no speech on a menu the mod has
    not been taught.  These four captures are the whole of the evidence that
    the two can be told apart, and each one is a screen the display pointer
    was never derived from.
    """
    print("\nMenus: read on request, never announced:")
    for name, want in MENUS.items():
        path = PROBE / f"{name}.bin"
        if not path.is_file():
            check(f"{name} present", False, "capture missing")
            continue
        pine = CapturePine(path.read_bytes())
        check(f"F12 still reads {name}", story.read_displayed(pine) == want,
              f"got {story.read_displayed(pine)!r}")
        voice = Recorder()
        reader = story.StoryReader(voice)
        for _ in range(4):
            reader.poll(pine)
        check(f"{name} is never announced by itself", voice.said == [],
              f"said {voice.said}")
        _, pointer = story.displayed(pine)
        check(f"{name} prose sits below the scene buffer",
              pointer < story.SCENE_TEXT_START, f"at 0x{pointer:08X}")

    for name in SCENES:
        path = PROBE / f"{name}.bin"
        if not path.is_file():
            continue
        _, pointer = story.displayed(CapturePine(path.read_bytes()))
        check(f"{name} sits inside the scene buffer",
              story.SCENE_TEXT_START <= pointer < story.SCENE_TEXT_END,
              f"at 0x{pointer:08X}")


def test_refusals() -> None:
    print("\nRefusals (each of these must produce silence, not a guess):")
    check("no BOM at the target",
          story.read_displayed(fake_ram("Hello there", bom=b"AB")) is None)
    check("pointer outside RAM",
          story.read_displayed(fake_ram("Hi", target=0x7F000000)) is None)
    check("control bytes in the text",
          story.read_displayed(fake_ram("bad\x01\x02text")) is None)
    check("move-list markup is not story text",
          story.read_displayed(fake_ram("Kamehameha\n%2Charge with the button"))
          is None)
    check("markup at the very start",
          story.read_displayed(fake_ram("$2Ultimate Blast")) is None)
    check("empty string",
          story.read_displayed(fake_ram("")) is None)
    # The game drew this during play. Speaking it was wrong, and the log could
    # not encode it, which took the whole guide down twice in one session.
    check("a CJK compatibility square is not dialogue",
          story.read_displayed(fake_ram("Nappa㌧ power")) is None)
    check("fullwidth move-list glyphs are refused",
          story.read_displayed(fake_ram("Kamehameha Ｌ２＋△"))
          is None)
    # The character select draws a badge after some names -- the game's own
    # name table has "Goku ®" and "Tien ㌧". Only a badge at the end
    # is dropped; the same glyph inside a line stays refused, as above.
    check("a name badge at the end is dropped",
          story.read_displayed(fake_ram("Goku ®")) == "Goku")
    check("the other name badge is dropped too",
          story.read_displayed(fake_ram("Tien ㌧")) == "Tien")


def test_accepts() -> None:
    print("\nAccepted (refusing these would go quiet on real lines):")
    check("plain prose",
          story.read_displayed(fake_ram("Who the heck are you?!"))
          == "Who the heck are you?!")
    # Eighteen real story boxes carry these; an ASCII-only check refused them.
    check("typographic apostrophe",
          story.read_displayed(fake_ram("Okay, Vegeta, now it’s your turn."))
          == "Okay, Vegeta, now it’s your turn.")
    check("ellipsis character",
          story.read_displayed(fake_ram("… and the next day,"))
          == "… and the next day,")
    check("line breaks become one spoken line",
          story.read_displayed(fake_ram("Goku and his \nfriends were \nhappy."))
          == "Goku and his friends were happy.")
    # The player asked for these to be spoken. Whether they still are depends
    # on where the game keeps one while it is on screen, which has never been
    # captured -- see the note on SCENE_TEXT_START. F12 reads it either way.
    check("a save notice is prose too",
          story.read_displayed(fake_ram("MEMORY CARD slot 1",
                                        target=MENU_TARGET))
          == "MEMORY CARD slot 1")
    # "#16" and "#18" are android names, not layout codes.
    check("a hash mid-line is a name, not markup",
          story.read_displayed(fake_ram("a third android, #16, is activated!"))
          == "a third android, #16, is activated!")


def test_behaviour() -> None:
    print("\nSpeaking behaviour:")
    pine = fake_ram("First line")
    voice = Recorder()
    reader = story.StoryReader(voice)
    reader.poll(pine)
    check("nothing is spoken on first sighting", voice.said == [])
    reader.poll(pine)
    check("spoken once it has settled", voice.said == ["First line"])
    reader.poll(pine)
    reader.poll(pine)
    check("an unchanged pointer stays silent", voice.said == ["First line"])

    moved = fake_ram("Second line")
    reader.poll(moved)
    reader.poll(moved)
    check("a new line is spoken", voice.said == ["First line", "Second line"])

    reader.poll(fake_ram("x", bom=b"AB"))
    reader.poll(moved)
    reader.poll(moved)
    check("a refused read does not re-speak the last line",
          voice.said == ["First line", "Second line"])

    reader.suspend()
    reader.poll(moved)
    reader.poll(moved)
    check("after suspend the scene is announced again",
          voice.said == ["First line", "Second line", "Second line"])


def test_echo_never_raises() -> None:
    """A log line the console cannot encode must not stop the guide.

    This is what actually reached the player: `Speaker.say` echoed to stdout,
    stdout was cp1252, and one character it could not encode raised out of the
    whole guide loop.  The reader no longer produces such a character, but the
    echo must survive one regardless -- it is a diagnostic, and a diagnostic
    that can kill the mod is worse than no diagnostic.
    """
    import io
    from bt2 import speech

    print("\nThe echo path:")
    saved = sys.stdout
    try:
        # A stream that behaves like a Windows console: cp1252, and it raises.
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252",
                                      errors="strict")
        try:
            speech._echo("Nappa ㌧ power")
            raised = False
        except Exception:
            raised = True
    finally:
        sys.stdout = saved
    check("an unencodable line does not raise", not raised)


def main() -> int:
    print("Story reader, offline checks")
    test_captures()
    test_menus_are_never_narrated()
    test_refusals()
    test_accepts()
    test_behaviour()
    test_echo_never_raises()
    failed = [name for name, passed in CHECKS if not passed]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} passed")
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
