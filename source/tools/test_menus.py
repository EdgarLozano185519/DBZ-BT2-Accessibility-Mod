"""Offline tests for screen detection, the F12 key, and the menu/story boundary.

No emulator, no player.  The captures in `reference/probe` are real EE RAM with
a screenshot beside each one, so which screen each of them *is* was read off a
picture rather than out of the code under test.  Twenty-one of them, covering
six screens and a cutscene, which is enough to insist that every marker matches
its own screen and no other.

The synthetic cases cover the two things captures cannot show: a screen whose
own block has moved -- which is what the player heard as menus reading their
subtitles instead of their options -- and the refusals.

    python test_menus.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from bt2 import menus, story

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "reference" / "probe"
CAPTURE_BASE = 0x00100000

# What each capture on disk is a picture of. Read off the screenshots saved
# beside them, never inferred from what the code says.
CAPTURES = {
    "auto0": "Main Menu",
    "main_after": "Main Menu",
    "press0": "Options",
    "library": "Dragon Library",
    "diff0": "Game Level",
    "events0": "Select Scenario",
    "posn0": "Select Scenario",
    "posn1": "Select Scenario",
    "posn2": "Select Scenario",
    "posn3": "Select Scenario",
    "posn4": "Select Scenario",
    "posn5": "Select Scenario",
    "pos0": "Title",
    "cut0": None, "cut1": None, "cut2": None, "cut3": None,
    "cut4": None, "cut5": None, "cut6": None, "cut7": None,
}

# The prose on screen in each capture, read off the same screenshots. F12 must
# reach these whether or not the screen has a recorded subtitle table.
PROSE = {
    "auto0": "You can set options during the game. What should I do...?",
    "press0": "During the game you can change the camera settings.",
    "library": ("You can read everyone's profile. "
                "We can study together if you want!"),
    "diff0": ("Set the Match level to your strength. "
              "You can always adjust it later!"),
    "events0": "What's wrong? Have you lost your nerve?",
    "posn0": "Man, I'm hungry...",
    "cut0": "I guess your little pet monsters weren't as strong as you thought.",
}


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

    def read8(self, address: int) -> int:
        return self._slice(address, 1)[0]

    def read32(self, address: int) -> int:
        return int.from_bytes(self._slice(address, 4), "little")

    def read_aligned_range(self, address: int, size: int, allow_large=False):
        if address % 8 or size % 8:
            raise ValueError("address and size must both be divisible by eight")
        return self._slice(address, size)


class ShiftedPine:
    """A capture with one region moved, as a fresh allocation would move it.

    Only the bytes matter, so the move is done by serving reads from
    `address - shift` inside the band. That reproduces exactly what the mod
    sees when the game rebuilds a menu's block somewhere else: the recorded
    marker address reads whatever is there now, and the real one is elsewhere
    in the band.
    """

    def __init__(self, inner: CapturePine, band: tuple[int, int], shift: int):
        self.inner = inner
        self.band = band
        self.shift = shift

    def _map(self, address: int) -> int:
        start, end = self.band
        if start <= address < end:
            moved = address - self.shift
            return moved if start <= moved < end else -1
        return address

    def read8(self, address: int) -> int:
        source = self._map(address)
        return 0 if source < 0 else self.inner.read8(source)

    def read32(self, address: int) -> int:
        return int.from_bytes(
            bytes(self.read8(address + n) for n in range(4)), "little"
        )

    def read_aligned_range(self, address: int, size: int, allow_large=False):
        if address % 8 or size % 8:
            raise ValueError("address and size must both be divisible by eight")
        start, end = self.band
        if end <= address or address + size <= start:
            return self.inner.read_aligned_range(address, size, allow_large)
        return bytes(self.read8(address + n) for n in range(size))


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


def load(name: str) -> CapturePine | None:
    path = PROBE / f"{name}.bin"
    if not path.is_file():
        return None
    return CapturePine(path.read_bytes())


def reader(story_reader=None) -> menus.MenuReader:
    return menus.MenuReader(Recorder(), story=story_reader)


def test_markers() -> None:
    """Every screen's markers match its own captures and no others."""
    print("\nMarkers, against every capture on disk:")
    for name, expected in CAPTURES.items():
        pine = load(name)
        if pine is None:
            check(f"{name} present", False, "capture missing")
            continue
        for screen in menus.SCREENS:
            if screen.weak_marker:
                continue        # Known not to be exclusive; see Title.
            want = screen.name == expected
            got = screen.present(pine)
            if want != got:
                check(f"{screen.name} on {name}", False,
                      f"expected {want}, got {got}")
    check("no named marker matched a screen it does not belong to",
          all(passed for _, passed in CHECKS))


def test_detection() -> None:
    """The mod names the screen the screenshot shows, and trusts its cursor."""
    print("\nDetection:")
    for name, expected in CAPTURES.items():
        pine = load(name)
        if pine is None:
            continue
        found, trusted = reader()._detect(pine)
        got = found.name if found else None
        check(f"{name} detects as {expected!r}", got == expected, f"got {got!r}")
        if expected is not None:
            check(f"{name} locates its cursor", trusted)


def test_prefers_the_option() -> None:
    """On a mapped menu the option is spoken and the subtitle is not."""
    print("\nThe menu option wins over the story reader:")
    for name, expected in CAPTURES.items():
        pine = load(name)
        if pine is None:
            continue
        menu = reader()
        menu.poll(pine, 0.0)          # Names the screen.
        menu.poll(pine, 0.1)          # Reads the cursor once.
        menu.poll(pine, 0.2)          # Settles it and speaks the option.
        screen = menu.screen
        readable = screen is not None and screen.readable
        check(f"{name}: reads_options is {readable}",
              menu.reads_options() == readable)

    pine = load("auto0")
    if pine is not None:
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        said = menu.speaker.said
        check("Main Menu says its name and the highlighted option",
              said[:2] == ["Main Menu", "Options"], f"said {said}")
        check("Main Menu does not say the option's subtitle",
              PROSE["auto0"] not in said, f"said {said}")

    pine = load("cut0")
    if pine is not None:
        menu = reader()
        menu.poll(pine, 0.0)
        check("a cutscene leaves the story reader to speak",
              not menu.reads_options())


def test_f12_reaches_every_screen() -> None:
    """F12 says the prose on screen, mapped table or not, named screen or not."""
    print("\nF12:")
    for name, want in PROSE.items():
        pine = load(name)
        if pine is None:
            continue
        menu = reader()
        menu.poll(pine, 0.0)
        menu._speak_subtitle(pine, 0.0)
        said = menu.speaker.said[-1]
        check(f"F12 on {name} reads the line on screen", said == want,
              f"said {said!r}")

    pine = load("cut0")
    if pine is not None:
        menu = reader()
        menu.poll(pine, 0.0)          # Unknown screen: a cutscene.
        menu._speak_subtitle(pine, 0.0)
        check("F12 answers on a screen the mod cannot name",
              menu.speaker.said[-1] == PROSE["cut0"],
              f"said {menu.speaker.said[-1]!r}")

    pine = load("cut0")
    if pine is not None:
        told = story.StoryReader(Recorder())
        menu = reader(told)
        menu.poll(pine, 0.0)
        menu._speak_subtitle(pine, 0.0)
        told.poll(pine)
        told.poll(pine)
        check("the story reader does not repeat what F12 just read",
              told.speaker.said == [], f"said {told.speaker.said}")

    pine = load("pos0")
    if pine is not None:
        menu = reader()
        menu.poll(pine, 0.0)
        menu._speak_subtitle(pine, 0.0)
        check("F12 says so when there is nothing written on screen",
              menu.speaker.said[-1] == "Nothing written on screen was found.",
              f"said {menu.speaker.said[-1]!r}")


class OverriddenPine:
    """A capture with single bytes replaced, to force a disagreement."""

    def __init__(self, inner, overrides: dict[int, int]):
        self.inner = inner
        self.overrides = overrides

    def read8(self, address: int) -> int:
        if address in self.overrides:
            return self.overrides[address]
        return self.inner.read8(address)

    def read32(self, address: int) -> int:
        return self.inner.read32(address)

    def read_aligned_range(self, address: int, size: int, allow_large=False):
        return self.inner.read_aligned_range(address, size, allow_large)


def test_the_two_cursor_copies() -> None:
    """The main menu is read twice over, and a disagreement means silence."""
    print("\nThe main menu's two copies of its cursor:")
    pine = load("auto0")
    if pine is None:
        check("auto0 present", False, "capture missing")
        return
    main = next(s for s in menus.SCREENS if s.name == "Main Menu")
    check("both copies read the same row",
          pine.read8(main.cursor) == pine.read8(main.mirror) == 8,
          f"near {pine.read8(main.cursor)}, far {pine.read8(main.mirror)}")

    disagreeing = OverriddenPine(pine, {main.mirror: 3})
    raw, label, settled = main.option(disagreeing)
    check("a disagreement is reported as unsettled, not named",
          not settled and label is None)

    menu = reader()
    for tick in range(5):
        menu.poll(disagreeing, tick * 0.1)
    check("so the option is never spoken",
          menu.speaker.said == ["Main Menu"], f"said {menu.speaker.said}")


class PatchedPine:
    """A capture with bytes written over it at chosen addresses."""

    def __init__(self, inner, patches: dict[int, bytes]):
        self.inner = inner
        self.patches = patches

    def _overlay(self, address: int, data: bytearray) -> bytes:
        for at, blob in self.patches.items():
            start = max(address, at)
            end = min(address + len(data), at + len(blob))
            if start < end:
                data[start - address:end - address] = blob[start - at:end - at]
        return bytes(data)

    def read8(self, address: int) -> int:
        return self._overlay(address, bytearray([self.inner.read8(address)]))[0]

    def read32(self, address: int) -> int:
        return int.from_bytes(
            bytes(self.read8(address + n) for n in range(4)), "little"
        )

    def read_aligned_range(self, address: int, size: int, allow_large=False):
        block = bytearray(
            self.inner.read_aligned_range(address, size, allow_large))
        return self._overlay(address, block)


def test_a_stale_marker_loses() -> None:
    """A marker left behind by a screen that has gone must not win.

    This is the fault the player hit. Backing out of Dragon Adventure leaves
    `mc_da_2_text_off_l` resident at 0x00D53440, so on the main menu two named
    screens matched, detection refused to name either, and the story reader --
    which speaks wherever the menu reader cannot -- read out the subtitle of
    every option they browsed past. On the Options screen the same leftover
    matched alone and announced "Select Scenario" over it.
    """
    print("\nA Dragon Adventure marker left resident after the mode was left:")
    base = load("auto0")
    if base is None:
        check("auto0 present", False, "capture missing")
        return
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")
    at, name = scenario.primary.first
    stale = PatchedPine(base, {at: name})

    check("the leftover really does match", scenario.present(stale))
    menu = reader()
    found, trusted = menu._detect(stale)
    check("the main menu is still named", found is not None
          and found.name == "Main Menu", f"got {found.name if found else None!r}")
    check("and its cursor is still read", trusted)

    menu = reader()
    for tick in range(4):
        menu.poll(stale, tick * 0.1)
    check("so the option is spoken, not the subtitle",
          menu.speaker.said[:2] == ["Main Menu", "Options"],
          f"said {menu.speaker.said}")

    # The same leftover on Options, where it used to name the wrong screen.
    options = load("press0")
    if options is not None:
        stale = PatchedPine(options, {at: name})
        found, _ = reader()._detect(stale)
        check("Options is not renamed Select Scenario",
              found is not None and found.name == "Options",
              f"got {found.name if found else None!r}")

    # And the screen itself must still work: outranked is not ignored.
    real = load("events0")
    if real is not None:
        found, trusted = reader()._detect(real)
        check("Select Scenario still names itself when it is up",
              found is not None and found.name == "Select Scenario")
        check("and its cursor is still read", trusted)


def test_a_silent_row_explains_itself() -> None:
    """Two cursor copies that will not agree must not just go quiet.

    Select Scenario's cursor was derived on a list of two entries, where
    position is only parity, so a counter with period two fits the presses as
    well as the real index does. A third scenario is exactly where that would
    come apart, and the failure would be permanent silence on the new row --
    indistinguishable from the mod being broken.
    """
    print("\nWhen a screen's two copies of the cursor disagree:")
    pine = load("events0")
    if pine is None:
        check("events0 present", False, "capture missing")
        return
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")
    # The near copy says row 3, the far one is stuck at parity 0.
    disagreeing = PatchedPine(pine, {scenario.cursor: b"\x02",
                                     scenario.mirror: b"\x00"})
    raw, label, settled = scenario.option(disagreeing)
    check("the read is unsettled, and no row is named",
          not settled and label is None)

    menu = reader()
    for tick in range(menus.UNSETTLED_BEFORE_SAYING + 4):
        menu.poll(disagreeing, tick * 0.1)
    said = menu.speaker.said
    check("the screen is named first", said[:1] == ["Select Scenario"],
          f"said {said}")
    explains = [line for line in said if "disagree" in line]
    check("the silence is explained exactly once", len(explains) == 1,
          f"said {said}")
    check("and F12 is offered as the way through",
          bool(explains) and "F12" in explains[0])

    # Agreement must still be the quiet, ordinary case.
    agreeing = PatchedPine(pine, {scenario.cursor: b"\x02",
                                  scenario.mirror: b"\x02"})
    menu = reader()
    for tick in range(menus.UNSETTLED_BEFORE_SAYING + 4):
        menu.poll(agreeing, tick * 0.1)
    check("a third scenario with both copies agreeing says its position",
          menu.speaker.said == ["Select Scenario",
                                "Scenario 3, name not known."],
          f"said {menu.speaker.said}")


def test_a_moved_block() -> None:
    """A menu whose own block has moved is still named, and found again.

    This is the fault the player heard: with the near marker gone the mod could
    not name the main menu at all, so the story reader read out the subtitle of
    every option they browsed past instead of the options.
    """
    print("\nWhen the main menu's own block has moved:")
    base = load("auto0")
    if base is None:
        check("auto0 present", False, "capture missing")
        return
    main = next(s for s in menus.SCREENS if s.name == "Main Menu")
    shift = 0x2000
    pine = ShiftedPine(base, main.search_band, shift)

    check("the recorded marker no longer matches", not main.primary.present(pine))
    check("the second signature still does", main.alternate.present(pine))

    menu = reader()
    found, trusted = menu._detect(pine)
    check("the screen is still named", found is not None and found.name == "Main Menu")
    check("but its cursor is not trusted yet", not trusted)

    check("the search finds how far it moved",
          menus.find_screen_shift(pine, main) == shift,
          f"got {menus.find_screen_shift(pine, main)}")

    menu = reader()
    for tick in range(5):
        menu.poll(pine, tick * 0.1)
    said = menu.speaker.said
    check("the player hears the screen, the search, then the option",
          said[:3] == ["Main Menu", "Looking for the menu.", "Options"],
          f"said {said}")
    check("and the cursor is read at the new address", menu.reads_options())

    # A shift the search cannot resolve must leave the cursor alone rather
    # than read whatever is at the recorded address.
    lost = ShiftedPine(base, (0x00A00000, 0x00B00000), 0x00A00000)
    menu = reader()
    for tick in range(4):
        menu.poll(pine=lost, now=tick * 0.1)
    check("a block that cannot be found leaves the options silent",
          not menu.reads_options())


def test_unmoved_captures_are_not_searched() -> None:
    """The search must not claim a shift on a screen that has not moved."""
    print("\nThe relocation search on captures that never moved:")
    main = next(s for s in menus.SCREENS if s.name == "Main Menu")
    for name in CAPTURES:
        pine = load(name)
        if pine is None:
            continue
        found = menus.find_screen_shift(pine, main)
        want = 0 if CAPTURES[name] == "Main Menu" else None
        check(f"{name}: search returns {want}", found == want, f"got {found}")


def main() -> int:
    if not PROBE.is_dir():
        print(f"No captures at {PROBE}; nothing to test against.")
        return 1
    test_markers()
    test_detection()
    test_prefers_the_option()
    test_f12_reaches_every_screen()
    test_the_two_cursor_copies()
    test_a_stale_marker_loses()
    test_a_silent_row_explains_itself()
    test_a_moved_block()
    test_unmoved_captures_are_not_searched()

    failed = [name for name, passed in CHECKS if not passed]
    print(f"\n{len(CHECKS) - len(failed)} of {len(CHECKS)} checks passed.")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
