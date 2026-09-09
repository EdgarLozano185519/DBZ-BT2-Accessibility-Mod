"""Offline tests for screen detection, the F12 key, and the menu/story boundary.

No emulator, no player.  The captures in `reference/probe` are real EE RAM with
a screenshot beside each one, so which screen each of them *is* was read off a
picture rather than out of the code under test.  Twenty-seven of them, covering
six screens and a cutscene, which is enough to insist that every marker matches
its own screen and no other -- in both directions, since a marker that matches
a screen it does not belong to is how three separate faults reached the player.

The scenario list gets the most attention here because it has cost the most.
Thirteen of the captures are of it, across four list lengths and several PCSX2
sessions, and every one is checked against the row its screenshot shows.

The synthetic cases cover what captures cannot: a screen whose own block has
moved, a marker left resident by a screen that has gone, two copies of a cursor
that will not agree, and a scenario unlocking that the mod has no name for.

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
    "charsel0": "Character Select",
    "csel0": "Character Select",
    "csel1": "Character Select",
    "csel2": "Character Select",
    "csel3": "Character Select",
    "csel4": "Character Select",
    "csel5": "Character Select",
    "csel6": "Character Select",
    "csel_p2": "Character Select",
    "csel20": "Character Select",
    "csel21": "Character Select",
    "csel22": "Character Select",
    "csel23": "Character Select",
    "csel24": "Character Select",
    "csel25": "Character Select",
    "csel26": "Character Select",
    "tourn0": "Tournament Character Select",
    # The Item Shop's Buy/Sell menu, reached from the main menu after a
    # Dragon Adventure session: the Select Scenario marker is still resident.
    "ishop0": "Item Shop",
    # The scenario list at each of its four rows, once a fourth unlocked.
    "row0": "Select Scenario",
    "row1": "Select Scenario",
    "row2": "Select Scenario",
    "row3": "Select Scenario",
    "scen3_fb": "Select Scenario",
    "scen5_final": "Select Scenario",
    "cut0": None, "cut1": None, "cut2": None, "cut3": None,
    "cut4": None, "cut5": None, "cut6": None, "cut7": None,
}

# The Item Shop, from two cued walks on 2026-09-08 (`shop*` through the
# Buy/Sell menu and into both lists, `scroll*` scrolling the Buy list and
# visiting every category tab). Each entry is the screen and the highlighted
# entry read off the screenshot beside the capture. "Buy Z Item" and "Sell Z
# Item" are variants of the Item Shop screen, not screens with markers of
# their own; see VARIANT_OF.
SHOP = {
    "shop0": ("Item Shop", "Sell Z Item"),
    "shop2": ("Item Shop", "Buy Z Item"),
    "shop7": ("Buy Z Item", "Health +1"),
    "shop8": ("Buy Z Item", "Ki +1"),
    "shop9": ("Buy Z Item", "Attack +1"),
    "shop10": ("Buy Z Item", "Dragon Homing Uses +1"),
    "shop13": ("Buy Z Item", "I am Champion!!"),
    "shop14": ("Buy Z Item", "Gravity Device"),
    "shop15": ("Buy Z Item", "Attack +1"),
    "shop16": ("Buy Z Item", "Ki +1"),
    "shop17": ("Item Shop", "Buy Z Item"),
    "shop18": ("Item Shop", "Sell Z Item"),
    "shop19": ("Sell Z Item", "Health +1"),
    "shop22": ("Sell Z Item", "Ki +1"),
    "shop23": ("Item Shop", "Sell Z Item"),
    "scroll5": ("Buy Z Item", "Speed +1"),
    "scroll6": ("Buy Z Item", "Equipment Slots +2"),
    "scroll8": ("Buy Z Item", "Blast 2 +1"),
    "scroll9": ("Buy Z Item", "Blast 1 +1"),
    "scroll12": ("Buy Z Item", "Defense +1"),
    "scroll13": ("Buy Z Item", "Attack +1"),
    "scroll19": ("Buy Z Item", "Ultimate Blast +1"),
    "scroll24": ("Buy Z Item", "Ultimate Blast +1"),
    "scroll26": ("Buy Z Item", "Z Item Fusion"),
    "scroll28": ("Buy Z Item", "Dragon Radar"),
    "scroll30": ("Item Shop", "Buy Z Item"),
    # The how-many picker (`qty*`, 2026-09-08): Up, Up, Down, Right, Right,
    # Left, then Triangle out, Right to the Secret tab, Cross on an item the
    # player cannot afford, Triangle out to the menu.
    "qty0": ("How many", "times 2"),
    "qty1": ("How many", "times 3"),
    "qty3": ("How many", "times 8"),
    "qty5": ("How many", "times 1"),
    "qty14": ("Buy Z Item", "King Yemma's Stamp"),
    "qty16": ("Buy Z Item", "Dragon Radar"),
    "qty17": ("Item Shop", "Buy Z Item"),
    "shop_stamp": ("How many", "times 1"),
}
CAPTURES.update({name: screen for name, (screen, _) in SHOP.items()})
VARIANT_OF = {"Buy Z Item": "Item Shop", "Sell Z Item": "Item Shop",
              "How many": "Item Shop"}

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
    # The character select draws a glyph after this name; F12 says the name.
    "charsel0": "Goku",
    "ishop0": "Hehehe, money makes the world go round. What'll you have today?",
    "shop7": "Which Z-item do you want?",
    "shop19": "Which Z-item do you want to sell?",
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


# Markers seen still resident on a capture of some other screen. Each entry is
# a measurement, not an allowance: the marker must carry
# `marker_outlives_screen`, detection must still name the capture's own screen
# (test_detection), and a stale match anywhere not listed here still fails.
# ishop0 is the first capture on disk taken after Dragon Adventure had been
# left, and it shows what the 2026-09-07 log reported: Select Scenario's
# marker at 0x00D53440 is still there. Game Level's is not.
STALE = {
    "ishop0": {"Select Scenario"},
}
STALE.update({name: {"Select Scenario"} for name in SHOP})


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
            want = screen.name == VARIANT_OF.get(expected, expected)
            if screen.name in STALE.get(name, ()):
                check(f"{screen.name} is flagged as outliving its screen",
                      screen.marker_outlives_screen)
                want = True     # Measured stale on this capture; see STALE.
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

    Silence for as long as the player stays on a screen is indistinguishable
    from the mod being broken, which is the fault this project exists to
    avoid.  Demonstrated on the main menu, whose two copies are a genuine pair.
    """
    print("\nWhen a screen's two copies of the cursor disagree:")
    pine = load("auto0")
    if pine is None:
        check("auto0 present", False, "capture missing")
        return
    main = next(s for s in menus.SCREENS if s.name == "Main Menu")
    disagreeing = PatchedPine(pine, {main.cursor: b"\x03",
                                     main.mirror: b"\x07"})
    raw, label, settled = main.option(disagreeing)
    check("the read is unsettled, and no row is named",
          not settled and label is None)

    menu = reader()
    for tick in range(menus.UNSETTLED_BEFORE_SAYING + 4):
        menu.poll(disagreeing, tick * 0.1)
    said = menu.speaker.said
    check("the screen is named first", said[:1] == ["Main Menu"], f"said {said}")
    explains = [line for line in said if "disagree" in line]
    check("the silence is explained exactly once", len(explains) == 1,
          f"said {said}")
    check("and F12 is offered as the way through",
          bool(explains) and "F12" in explains[0])

    # Agreement must still be the quiet, ordinary case.
    agreeing = PatchedPine(pine, {main.cursor: b"\x03", main.mirror: b"\x03"})
    menu = reader()
    for tick in range(menus.UNSETTLED_BEFORE_SAYING + 4):
        menu.poll(agreeing, tick * 0.1)
    check("a row both copies agree on is simply spoken",
          menu.speaker.said == ["Main Menu", "Dueling"],
          f"said {menu.speaker.said}")


# The three rows of the grown scenario list, read live on 2026-09-07 with a
# screenshot saved beside each one. `0x00B0536C` is the cursor, `0x00B05370`
# the length. The fourth column is the address that used to be the cursor and
# reads 1 for two different rows, which is what refutes it.
LIVE_ROWS = [
    ("Fateful Brothers", 2, 3, 1),
    ("Saiyan Saga", 0, 3, 0),
    ("Tree of Might", 1, 3, 1),
]

# The same again once a fourth scenario unlocked, from row0-3.png. Lord Slug
# was inserted at index 2 and moved Fateful Brothers from 2 to 3 -- the second
# insertion this screen has seen. Note the last column: the refuted address
# reads 0, 1, 0, 1 here, which is what it always was.
LIVE_ROWS_FOUR = [
    ("Saiyan Saga", 0, 4, 0),
    ("Tree of Might", 1, 4, 1),
    ("Lord Slug", 2, 4, 0),
    ("Fateful Brothers", 3, 4, 1),
]


def test_the_grown_scenario_list() -> None:
    """Three scenarios, and the new one was inserted rather than appended."""
    print("\nThe scenario list, at the three rows photographed live:")
    base = load("scen3_fb")
    if base is None:
        check("scen3_fb present", False, "capture missing")
        return
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")

    check("the refuted address is no longer the cursor",
          scenario.cursor == 0x00B0536C)
    check("and it is not kept as a cross-check either", scenario.mirror is None)

    seen = set()
    for shown, cursor, count, refuted in LIVE_ROWS:
        pine = PatchedPine(base, {scenario.cursor: bytes([cursor]),
                                  scenario.count_address: bytes([count]),
                                  0x00D53625: bytes([refuted])})
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        check(f"{shown} is named", menu.speaker.said == ["Select Scenario", shown],
              f"said {menu.speaker.said}")
        seen.add(refuted)
    check("the refuted address really does repeat itself across rows",
          len(seen) < len(LIVE_ROWS))

    # The two-entry captures still work, because the names are keyed by length.
    for name, want in (("posn0", "Saiyan Saga"), ("events0", "Fateful Brothers")):
        pine = load(name)
        if pine is None:
            continue
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        check(f"{name} still says {want!r} on the two-entry list",
              menu.speaker.said == ["Select Scenario", want],
              f"said {menu.speaker.said}")


def test_the_four_entry_list() -> None:
    """Four scenarios, each row read against its own capture and screenshot.

    Every row here has its own 31 MB capture, so unlike the three-entry case
    these are not patched -- the reader is answering the game's own memory.
    """
    print("\nThe scenario list once a fourth unlocked, row by row:")
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")
    for index, (shown, cursor, count, refuted) in enumerate(LIVE_ROWS_FOUR):
        pine = load(f"row{index}")
        if pine is None:
            check(f"row{index} present", False, "capture missing")
            continue
        check(f"row{index} really is cursor {cursor} of {count}",
              pine.read8(scenario.cursor) == cursor
              and pine.read8(scenario.count_address) == count)
        check(f"row{index}'s refuted address reads {refuted}",
              pine.read8(0x00D53625) == refuted)
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        check(f"{shown} is named", menu.speaker.said == ["Select Scenario", shown],
              f"said {menu.speaker.said}")

    refuted = {row[3] for row in LIVE_ROWS_FOUR}
    check("the refuted address cannot tell four rows apart",
          len(refuted) < len(LIVE_ROWS_FOUR), f"took values {sorted(refuted)}")


# What each capture's screenshot shows, for the whole scenario-list history.
# Twelve pictures across three list lengths and several PCSX2 sessions.
SCENARIO_SHOTS = [
    ("posn0", "Saiyan Saga"), ("posn1", "Fateful Brothers"),
    ("posn2", "Saiyan Saga"), ("posn3", "Fateful Brothers"),
    ("posn4", "Saiyan Saga"), ("posn5", "Fateful Brothers"),
    ("events0", "Fateful Brothers"),
    ("scen3_fb", "Fateful Brothers"),
    ("row0", "Saiyan Saga"), ("row1", "Tree of Might"),
    ("row2", "Lord Slug"), ("row3", "Fateful Brothers"),
    ("scen5_final", "Final Battle"),
]


def test_the_scenario_is_asked_for_by_name() -> None:
    """The row number shifts at every unlock; the scenario number does not.

    `0x00B05308` is the game's own list of which scenarios it is showing, so
    the mod asks what a row *is* rather than assuming the row number still
    means what it did before. This is what makes an unlock cost one unnamed
    row instead of all of them.
    """
    print("\nNaming the row by which scenario it is:")
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")

    for name, shown in SCENARIO_SHOTS:
        pine = load(name)
        if pine is None:
            check(f"{name} present", False, "capture missing")
            continue
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        check(f"{name} says {shown!r}, as its screenshot does",
              menu.speaker.said == ["Select Scenario", shown],
              f"said {menu.speaker.said}")

    # A list's contents cannot depend on where the cursor is sitting.
    for group, label in ((["posn0", "posn1", "posn3", "events0"], "two"),
                         (["row0", "row1", "row2", "row3"], "four")):
        seen = set()
        for name in group:
            pine = load(name)
            if pine is not None:
                seen.add(tuple(scenario.scenario_ids(pine)))
        check(f"the {label}-entry list reads the same at every row",
              len(seen) == 1, f"got {seen}")

    # And the numbers explain why the list grows the way it does.
    pine = load("row0")
    if pine is not None:
        check("the four-entry list is [0, 1, 2, 21]",
              scenario.scenario_ids(pine) == [0, 1, 2, 21],
              f"got {scenario.scenario_ids(pine)}")
        check("which is sorted, so Fateful Brothers stays last",
              scenario.scenario_ids(pine) == sorted(scenario.scenario_ids(pine)))


def test_the_five_entry_list() -> None:
    """The fifth scenario, against the game's own memory rather than a patch.

    This is the case the design was built for, and it happened: Final Battle
    unlocked as number 3, landed between Lord Slug and Fateful Brothers exactly
    where the numbers say it must, and cost one row instead of five. The
    capture is of the row the player was sitting on, so the other rows are
    reached by moving the cursor within it -- the list itself is untouched.
    """
    print("\nThe five-entry list, from the capture of it:")
    base = load("scen5_final")
    if base is None:
        check("scen5_final present", False, "capture missing")
        return
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")

    check("the game lists [0, 1, 2, 3, 21]",
          scenario.scenario_ids(base) == [0, 1, 2, 3, 21],
          f"got {scenario.scenario_ids(base)}")
    check("still sorted, so Fateful Brothers stays last",
          scenario.scenario_ids(base) == sorted(scenario.scenario_ids(base)))

    expected = ["Saiyan Saga", "Tree of Might", "Lord Slug", "Final Battle",
                "Fateful Brothers"]
    for row, want in enumerate(expected):
        pine = PatchedPine(base, {scenario.cursor: bytes([row])})
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        check(f"row {row} says {want!r}",
              menu.speaker.said == ["Select Scenario", want],
              f"said {menu.speaker.said}")

    # A row past the end of the list is not an answer.
    pine = PatchedPine(base, {scenario.cursor: b"\x06"})
    menu = reader()
    for tick in range(6):
        menu.poll(pine, tick * 0.1)
    check("a row beyond the list is read again rather than named",
          menu.speaker.said == ["Select Scenario"], f"said {menu.speaker.said}")


# Where the game's own scenario-name table sat in the captures that have it.
# It is loaded during play rather than with the screen, so it is absent from
# most captures and from a freshly booted emulator -- which is why the names
# are shipped rather than read at runtime.
NAME_TABLE = 0x01089702
NAME_GRANULE = 0x40


def walk_name_table(pine, start=NAME_TABLE, granules=40):
    """The names in the game's table, joining a granule that ran over.

    Two names are longer than a granule and continue into the next, so the
    table has to be walked. Indexing it arithmetically returns the fragments
    "n" and "ion" -- the same trap the event-name table sets.
    """
    names, pending, index = [], "", 0
    while index < granules:
        text, ended = [], False
        for step in range(0, NAME_GRANULE, 2):
            try:
                low = pine.read8(start + index * NAME_GRANULE + step)
                high = pine.read8(start + index * NAME_GRANULE + step + 1)
            except Exception:
                return names
            if low == 0 and high == 0:
                ended = True
                break
            text.append(chr(low | (high << 8)))
        pending += "".join(text)
        index += 1
        if ended:
            names.append(pending)
            pending = ""
    return names


def test_the_names_match_the_game_s_own_table() -> None:
    """Every shipped scenario name must be the one the game itself stores.

    The names were walked out of the game's table rather than typed from
    screenshots, and this is what keeps them honest: if the table and the
    shipped list ever disagree, one of them has been edited by hand.
    """
    print("\nThe shipped names against the game's own table:")
    pine = load("row0")
    if pine is None:
        check("row0 present", False, "capture missing")
        return
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")
    table = walk_name_table(pine)
    check("the table was found in the capture", len(table) > 24,
          f"walked {len(table)} entries")

    for number, name in sorted(scenario.labels_by_id.items()):
        check(f"scenario {number} is {name!r} in the game too",
              number < len(table) and table[number] == name,
              f"table says {table[number]!r}" if number < len(table) else "past end")

    # The five that were read off screenshots, which anchor all the rest.
    for name, number in (("Saiyan Saga", 0), ("Tree of Might", 1),
                         ("Lord Slug", 2), ("Final Battle", 3),
                         ("Fateful Brothers", 21)):
        check(f"{name!r} is anchored at {number} by a screenshot",
              scenario.labels_by_id.get(number) == name)

    # Past the scenarios the table turns into battle stages. Speaking one of
    # those as a scenario would be exactly the confident error to avoid.
    check("the table continues into stage names",
          len(table) > 25 and table[25] == "Wasteland", f"got {table[25:26]}")
    check("and none of them is shipped as a scenario",
          all(number <= 24 for number in scenario.labels_by_id))


def test_a_newly_unlocked_scenario_costs_one_row() -> None:
    """An unknown scenario number must not disturb the names around it.

    Before the numbers were found, a longer list meant no names at all: the
    player heard "Scenario 1 of 4, name not known" on every row. Now only the
    new one is unnamed, and the rest keep working. Synthetic, because it has to
    stay true of a scenario nobody has seen yet -- every real number is named.
    """
    print("\nWhen a sixth scenario unlocks:")
    base = load("scen5_final")
    if base is None:
        check("scen5_final present", False, "capture missing")
        return
    scenario = next(s for s in menus.SCREENS if s.name == "Select Scenario")
    # Every number the game uses is now named, so this is a number past
    # the end of its table -- the only way left to be unnamed.
    grown = {scenario.count_address: b"\x06"}
    for row, which in enumerate([0, 1, 2, 3, 40, 21]):
        grown[scenario.id_array + row * scenario.id_stride] = bytes([which])

    expected = ["Saiyan Saga", "Tree of Might", "Lord Slug", "Final Battle",
                "Scenario 5 of 6, name not known.", "Fateful Brothers"]
    for row, want in enumerate(expected):
        pine = PatchedPine(base, {**grown, scenario.cursor: bytes([row])})
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        check(f"row {row} says {want!r}",
              menu.speaker.said == ["Select Scenario", want],
              f"said {menu.speaker.said}")

    check("exactly one row of six is unnamed",
          sum("not known" in want for want in expected) == 1)


# Player 1's highlighted character in each character-select capture, read
# off the screenshot beside it. charsel0 was taken before the cued scan and
# the seven csel captures during it, across both axes of the grid.
CHARACTERS = {
    "charsel0": "Goku",
    "csel0": "Kid Gohan",
    "csel1": "Teen Gohan",
    "csel2": "Kid Gohan",
    "csel3": "Tien",
    "csel4": "Chiaotzu",
    "csel5": "Teen Gohan",
    "csel6": "Kid Gohan",
    # Player 1 confirmed on Goku, the cursor on player 2's row.
    "csel_p2": "Goku",
}

# Player 2's highlighted character in the same captures. It was never moved
# during the first scan, so every one of those shows Kid Gohan.
PLAYER_TWO = "Kid Gohan"

# The second cued scan, with player 1 confirmed on Goku and the cursor on
# player 2's grid: Right, Right, Left, Down, Right, Up, Left. Player 2's
# pointer was found from captures in which player 2 had never moved, so these
# seven are the transitions it was not derived from. Read off the screenshots.
PLAYER_TWO_MOVED = {
    "csel20": "Teen Gohan",
    "csel21": "Gohan",
    "csel22": "Teen Gohan",
    "csel23": "Chiaotzu",
    "csel24": "Trunks (Sword)",
    "csel25": "Piccolo",
    "csel26": "Gohan",
}


class RepointedPine:
    """A capture with one 32-bit word replaced, to move a draw pointer."""

    def __init__(self, inner, address: int, value: int):
        self.inner = inner
        self.address = address
        self.value = value

    def read8(self, address: int) -> int:
        return self.inner.read8(address)

    def read32(self, address: int) -> int:
        if address == self.address:
            return self.value
        return self.inner.read32(address)

    def read_aligned_range(self, address: int, size: int, allow_large=False):
        return self.inner.read_aligned_range(address, size, allow_large)


class ErasedPine(CapturePine):
    """A capture with one region zeroed, as if a sprite name were gone."""

    def __init__(self, inner: CapturePine, address: int, size: int):
        data = bytearray(inner.data)
        start = address - inner.base
        data[start:start + size] = bytes(size)
        super().__init__(bytes(data), inner.base)


def test_the_weak_marker_needs_a_silent_screen() -> None:
    """The title's raw signature is refused while the game draws text."""
    print("\nThe weak marker:")
    title = next(s for s in menus.SCREENS if s.name == "Title")
    pos0 = load("pos0")
    if pos0 is not None:
        check("the title capture has no text on screen",
              not menus.MenuReader._text_on_screen(pos0))
        check("so the title screen is still named",
              reader()._detect(pos0)[0] is title)
    # Every capture where the signature matched beside text: with that
    # screen's own marker erased, the old rule would have said "New Game".
    for name, expected in CAPTURES.items():
        pine = load(name)
        if pine is None or expected in (None, "Title"):
            continue
        if not title.present(pine):
            continue
        own = next(s for s in menus.SCREENS
                   if s.name == VARIANT_OF.get(expected, expected))
        erased = ErasedPine(pine, own.marker_address, len(own.marker))
        found, _ = reader()._detect(erased)
        check(f"{name} without its marker is not called Title",
              found is not title, f"got {found.name if found else None!r}")


def test_player_two() -> None:
    """Player 2's slot speaks when its own pointer moves, with its prefix once."""
    print("\nPlayer 2:")
    screen = next(s for s in menus.SCREENS if s.name == "Character Select")
    pine = load("csel_p2")
    if pine is None:
        check("csel_p2 present", False, "capture missing")
        return
    names = screen.displayed_names(pine)
    check("both slots read on the player 2 capture",
          names == ("Goku", PLAYER_TWO), f"read {names}")
    for name in CHARACTERS:
        other = load(name)
        if other is not None:
            got = screen.displayed_names(other)[1]
            check(f"{name}: player 2 reads {PLAYER_TWO!r}", got == PLAYER_TWO,
                  f"read {got!r}")
    for name, want in PLAYER_TWO_MOVED.items():
        other = load(name)
        if other is None:
            check(f"{name} present", False, "capture missing")
            continue
        got = screen.displayed_names(other)
        check(f"{name}: player 1 still Goku, player 2 {want!r}",
              got == ("Goku", want), f"read {got}")

    # Move player 2's pointer to Tien, then Chiaotzu, then move player 1.
    tien, chiaotzu, goku = 0x00D61EC0, 0x00D61F00, 0x00D61C00
    menu = reader()
    for tick in range(4):
        menu.poll(pine, tick * 0.1)
    moved = RepointedPine(pine, story.SECOND_DISPLAY_POINTER, tien)
    for tick in range(3):
        menu.poll(moved, 1 + tick * 0.1)
    moved = RepointedPine(pine, story.SECOND_DISPLAY_POINTER, chiaotzu)
    for tick in range(3):
        menu.poll(moved, 2 + tick * 0.1)
    both = RepointedPine(
        RepointedPine(pine, story.SECOND_DISPLAY_POINTER, chiaotzu),
        story.DISPLAY_POINTER, goku + 0x40 * 4)          # Kid Gohan
    for tick in range(3):
        menu.poll(both, 3 + tick * 0.1)
    said = menu.speaker.said
    check("player 2 is prefixed once, then bare, then player 1 is bare",
          said == ["Character Select", "Goku", "Player 2: Tien", "Chiaotzu",
                   "Kid Gohan"],
          f"said {said}")


# The Dragon Tournament entry screen, one visit: Yamcha highlighted, and the
# second draw slot holding a menu line that must not be spoken as a player.
TOURNAMENT = {"tourn0": "Yamcha"}


def test_character_select_names() -> None:
    """The highlighted character is read from the game's own text."""
    print("\nCharacter Select:")
    expected = [(n, "Character Select", w) for n, w in CHARACTERS.items()]
    expected += [(n, "Tournament Character Select", w)
                 for n, w in TOURNAMENT.items()]
    for name, screen_name, want in expected:
        pine = load(name)
        if pine is None:
            check(f"{name} present", False, "capture missing")
            continue
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        said = menu.speaker.said
        check(f"{name} says {want!r}", said == [screen_name, want],
              f"said {said}")
        told = story.StoryReader(Recorder())
        told.poll(pine)
        told.poll(pine)
        check(f"{name}: the story reader stays quiet", told.speaker.said == [],
              f"said {told.speaker.said}")


def test_item_shop() -> None:
    """The shop's menu and both lists speak what the screenshots show."""
    print("\nItem Shop:")
    for name, (screen_name, want) in SHOP.items():
        pine = load(name)
        if pine is None:
            check(f"{name} present", False, "capture missing")
            continue
        menu = reader()
        for tick in range(4):
            menu.poll(pine, tick * 0.1)
        said = menu.speaker.said
        check(f"{name} says {want!r}", said == [screen_name, want],
              f"said {said}")
        told = story.StoryReader(Recorder())
        told.poll(pine)
        told.poll(pine)
        check(f"{name}: the story reader stays quiet", told.speaker.said == [],
              f"said {told.speaker.said}")

    # Walking from the menu into the Buy list and back: the variant is named
    # on each change, and the option or item after it.
    menu_up, list_up, back = load("shop2"), load("shop7"), load("shop17")
    if menu_up and list_up and back:
        menu = reader()
        for tick in range(4):
            menu.poll(menu_up, tick * 0.1)
        for tick in range(4):
            menu.poll(list_up, 1 + tick * 0.1)
        for tick in range(4):
            menu.poll(back, 2 + tick * 0.1)
        check("menu, list, menu is spoken as such",
              menu.speaker.said == ["Item Shop", "Buy Z Item", "Buy Z Item",
                                    "Health +1", "Item Shop", "Buy Z Item"],
              f"said {menu.speaker.said}")

    # A state byte this build has not mapped -- a dialog the walks never
    # reached -- names the shop and reads nothing, and still counts as a menu
    # inside Adventure so guidance stays off.
    if menu_up:
        shop = next(s for s in menus.SCREENS if s.name == "Item Shop")
        unknown = PatchedPine(menu_up, {shop.state_address: b"\x40"})
        menu = reader()
        for tick in range(4):
            menu.poll(unknown, tick * 0.1)
        check("an unmapped shop state names the shop only",
              menu.speaker.said == ["Item Shop"], f"said {menu.speaker.said}")
        check("and does not read options", not menu.reads_options())
        check("and still holds the Adventure gate",
              menu.in_adventure_menu(unknown))
    # The refusal: Cross on an item the player cannot afford leaves the list
    # up and changes only Baba's line. qty15 and qty16 both show the refusal
    # already (it is stale from an earlier one), so the prompt is put back
    # on the first capture and the change is watched.
    before, after = load("qty15"), load("qty16")
    if before and after:
        import struct
        asking = PatchedPine(before, {0x008C6244: struct.pack("<I", 0x00B05080)})
        menu = reader()
        for tick in range(4):
            menu.poll(asking, tick * 0.1)
        check("the list names the item, not the prompt, on arrival",
              menu.speaker.said == ["Buy Z Item", "Dragon Radar"],
              f"said {menu.speaker.said}")
        for tick in range(4):
            menu.poll(after, 1 + tick * 0.1)
        check("a refusal is spoken when Baba's line changes",
              menu.speaker.said[2:] == ["Hey, you don't have enough money!!"],
              f"said {menu.speaker.said}")

    # The picker: the quantity is spoken as it moves, and the stale line in
    # Baba's box is not.
    steps = [load(f"qty{n}") for n in (0, 1, 2, 3, 5)]
    if all(steps):
        menu = reader()
        for index, pine in enumerate(steps):
            for tick in range(4):
                menu.poll(pine, index + tick * 0.1)
        check("the picker speaks each quantity once",
              menu.speaker.said == ["How many", "times 2", "times 3",
                                    "times 2", "times 8", "times 1"],
              f"said {menu.speaker.said}")
        check("and never Baba's stale line",
              not any("money" in line for line in menu.speaker.said))
        # The Buy/Sell cursor's two copies disagree off the menu, so the base
        # screen must never read it: the list captures prove the copies apart.
        selling = load("shop19")
        if selling:
            variant = shop.resolve(menu_up)
            raw, label, settled = variant.option(selling)
            check("the menu cursor is refused on the Sell list capture",
                  not settled, f"raw {raw}, label {label!r}")


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
    test_the_grown_scenario_list()
    test_the_four_entry_list()
    test_the_scenario_is_asked_for_by_name()
    test_the_five_entry_list()
    test_the_names_match_the_game_s_own_table()
    test_a_newly_unlocked_scenario_costs_one_row()
    test_character_select_names()
    test_player_two()
    test_item_shop()
    test_the_weak_marker_needs_a_silent_screen()
    test_a_moved_block()
    test_unmoved_captures_are_not_searched()

    failed = [name for name, passed in CHECKS if not passed]
    print(f"\n{len(CHECKS) - len(failed)} of {len(CHECKS)} checks passed.")
    for name in failed:
        print(f"  FAILED: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
