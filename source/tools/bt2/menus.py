"""Announcing menus: which screen is showing, and what is highlighted.

BT2's menu labels are pre-rendered artwork, so nothing in memory spells "Dragon
Adventure".  The game keeps the *index* of the highlighted option, and the words
come from the tables here -- the only place that text exists, and the only thing
that can ever be translated.

Prose is the opposite.  On-screen subtitles are held as verbatim UTF-16LE, so
those are read from the game rather than authored, which also covers text that
was never extracted from the disc.

The screen must be identified before any cursor is read: each menu reuses the
same memory, so 0x00AA12A8 is the main menu's cursor but reads 163 on Options
and 208 on Dragon Library.  Screens identify themselves, because each loads its
own table of sprite names -- Options is recognisable by the literal text
"mc_icon_saveload".  A readable marker beats a state number, which can only be
trusted rather than checked.

**A screen may be recognised by more than one signature, and they are not
equal.**  The main menu's marker sits in the same allocation as its cursor, so
finding it says where the cursor is as well.  Its second signature lives in a
different block entirely and proves only that the screen is up.  That
distinction is the whole point: naming a screen from evidence that says nothing
about its cursor, and then reading that cursor anyway, is how a menu comes to
announce an option that was never highlighted.

When only the far signature matches, the near block has moved, and it is looked
for by the game's own sprite name inside a narrow band.  Same technique as the
subtitle search below, and for the same reason: nothing searched for here is a
line of game text, so none of it is tied to English.

The subtitle addresses were recorded in one PCSX2 run and the block moves
between runs, so they are treated as a starting guess rather than a fact.  When
they stop reading as text the block is found again by its shape -- ten lines at
known spacing -- and the offset is remembered for the session.  F12 no longer
depends on any of that succeeding: it falls back to the pointer the game draws
with, which reads every screen and has not moved between runs.

Addresses and their evidence are recorded in docs/memory-map.md.
"""

from __future__ import annotations

import collections
import ctypes

from .hotkeys import desktop_input_allowed
from .speech import note

MAX_SUBTITLE_BYTES = 400

# The band the subtitle block has been seen in, searched in bounded steps.
# Reading all 32 MiB starves the emulator (see scan.py), so the search is
# deliberately narrow and only runs when the recorded addresses have failed.
SUBTITLE_SEARCH_START = 0x00C00000
SUBTITLE_SEARCH_END = 0x00D00000
SUBTITLE_SEARCH_STEP = 0x80000
# Searching costs the player a pause, so never repeat it faster than this.
SUBTITLE_SEARCH_INTERVAL = 20.0
# A line long enough that ten of them at fixed spacing cannot be chance.
MIN_ANCHOR_CHARACTERS = 8

# How many distinct diagnostic lines to remember, so none repeats.
NOTED_LINES = 16

# How many consecutive frames the two copies of a cursor may disagree before
# the mod says so out loud. One disagreement is a read landing mid-update and
# is expected; a run of them means the two addresses no longer mean the same
# thing, and the player is owed an explanation rather than silence. At roughly
# seven passes a second this is about three seconds.
UNSETTLED_BEFORE_SAYING = 20

# The same rate limit, for the search that relocates a menu's own block.
SCREEN_SEARCH_INTERVAL = 20.0
SCREEN_SEARCH_STEP = 0x80000

# A signature spanning less than this is read in one PINE transaction instead
# of a byte at a time. Six screens checked per pass at one request per byte was
# ninety round trips a frame; this is six.
BLOCK_READ_LIMIT = 0x1000

# PCSX2 binds F1 to F6, F8 and F9. F12 is unbound, so the mod can claim it.
VK_F12 = 0x7B

# The highest row number that will ever be spoken as a bare position. A
# cursor reading beyond this is far likelier to be a bad read than a menu
# that long, and inventing a row number from garbage would be its own
# confident error.
MAX_UNNAMED_ROW = 16


def _read_ascii(pine, address: int, count: int) -> bytes:
    return bytes(pine.read8(address + offset) for offset in range(count))


class Signature:
    """Sprite names the game itself loaded, at addresses recorded from captures.

    Every name must be present for the signature to match.  One name is enough
    where that name is unique to the screen across every capture on disk; where
    the only unique evidence is a run of ordinary names in a per-screen table,
    several at fixed offsets are demanded together.  That is the same argument
    the subtitle search makes: a coincidence would have to reproduce the whole
    layout, not just one string.
    """

    def __init__(self, names, near_cursor: bool = False):
        self.names = tuple(names)
        # True when this signature lives in the same allocation as the screen's
        # cursor, so matching it also says where the cursor is. False for a
        # signature elsewhere in memory, which names the screen and no more.
        self.near_cursor = near_cursor

    @property
    def first(self) -> tuple[int, bytes]:
        return self.names[0]

    def present(self, pine, shift: int = 0) -> bool:
        low = min(address for address, _ in self.names) + shift
        high = max(address + len(name) for address, name in self.names) + shift
        if high - low <= BLOCK_READ_LIMIT:
            start = low & ~7
            size = high - start
            size += -size % 8
            try:
                block = pine.read_aligned_range(start, size)
            except Exception:
                return self._present_bytewise(pine, shift)
            for address, name in self.names:
                begin = address + shift - start
                if block[begin:begin + len(name)] != name:
                    return False
            return True
        return self._present_bytewise(pine, shift)

    def _present_bytewise(self, pine, shift: int) -> bool:
        for address, name in self.names:
            if _read_ascii(pine, address + shift, len(name)) != name:
                return False
        return True


class Screen:
    """A menu: how to recognise it, where its cursor is, what its rows say."""

    def __init__(self, name, marker_address, marker, cursor=None, stride=1,
                 labels=None, subtitles=None, mirror=None, mirror_stride=1,
                 in_adventure=False, weak_marker=False, unknown_row=None,
                 alternate=None, search_band=None,
                 marker_outlives_screen=False):
        self.name = name
        self.marker_address = marker_address
        self.marker = marker
        self.cursor = cursor
        self.stride = stride
        self.labels = labels or {}
        self.subtitles = subtitles or {}
        # A second copy of the same cursor, kept by the game elsewhere in
        # memory. Where one exists it is read too, and the option is spoken
        # only if both agree -- see option().
        self.mirror = mirror
        self.mirror_stride = mirror_stride
        # True for menus that appear while the Dragon Adventure HUD detector
        # still reports gameplay. Those need the guide told explicitly that a
        # menu is up; see MenuReader.in_adventure_menu.
        self.in_adventure = in_adventure
        # A marker that is a raw byte signature rather than a sprite name is
        # weaker evidence: it can and does turn up on screens it has nothing to
        # do with. Such a screen is only accepted when no named marker matches.
        self.weak_marker = weak_marker
        # How to describe a row this screen has no name for, if it should be
        # described at all. Most menus here are a fixed length, so an index off
        # the end of the table means a bad read and silence is right. A list
        # that grows with the player's progress is different: an unnamed row is
        # the expected consequence of playing the game, and saying nothing
        # leaves the player unable to tell a new scenario from a broken mod.
        self.unknown_row = unknown_row
        # The recorded marker, which sits beside the cursor.
        self.primary = Signature([(marker_address, marker)], near_cursor=True)
        # Evidence from a second allocation, which outlives the first. It names
        # the screen; it never vouches for the cursor.
        self.alternate = alternate
        # True where the marker has been seen still resident after the screen
        # was left. Such a marker is real evidence that the screen was up at
        # some point and no evidence that it is up now, so it loses to any
        # marker not known to do this. Set from what was observed, never from
        # what seems likely -- see MenuReader._detect.
        self.marker_outlives_screen = marker_outlives_screen
        # Where to look for the near block when it has moved, as (start, end).
        # Narrow on purpose: the marker name occurs elsewhere in RAM, and a
        # band wide enough to catch every copy could not tell them apart.
        self.search_band = search_band

    @property
    def readable(self) -> bool:
        return self.cursor is not None

    def present(self, pine, shift: int = 0) -> bool:
        if self.primary.present(pine, shift):
            return True
        return self.alternate is not None and self.alternate.present(pine)

    def option(self, pine, shift: int = 0) -> tuple[int, str | None, bool]:
        """Return the raw cursor, its label, and whether the read is settled.

        An unsettled read is one the mirrors disagreed about, which means try
        again.  That is different from a value this screen has no option for,
        where the right answer is a permanent silence.  Conflating the two
        would let one unlucky frame mute an option until the player navigated
        away and back.
        """
        raw = pine.read8(self.cursor + shift)
        if raw % self.stride:
            return raw, None, True
        index = raw // self.stride
        if self.mirror is not None:
            # The mirror is a different allocation and does not travel with the
            # near block, so the shift is deliberately not applied to it.
            other = pine.read8(self.mirror)
            if other % self.mirror_stride:
                return raw, None, False
            if other // self.mirror_stride != index:
                # The two copies are mid-update, or one of them has moved to a
                # different address in this run. Either way, saying nothing is
                # better than naming an option on a coin toss.
                return raw, None, False
        return raw, self.labels.get(index), True

    def unknown_row_label(self, raw: int) -> str | None:
        """Describe a row with no name, or return None to stay silent."""
        if self.unknown_row is None:
            return None
        if self.stride and raw % self.stride:
            return None          # Not a whole index; this is a bad read.
        index = raw // self.stride
        if index > MAX_UNNAMED_ROW:
            return None
        return self.unknown_row.format(position=index + 1)


def read_subtitle(pine, address: int) -> str | None:
    """Read a null-terminated UTF-16LE line, or None if it is not text.

    Subtitle addresses were recorded in one PCSX2 run and the block may move
    between runs, so anything that does not look like a sentence is refused
    rather than spoken.
    """
    raw = bytearray()
    for offset in range(0, MAX_SUBTITLE_BYTES, 2):
        low = pine.read8(address + offset)
        high = pine.read8(address + offset + 1)
        if low == 0 and high == 0:
            break
        if high != 0 or not (low in (10, 13) or 32 <= low < 127):
            return None
        raw.append(low)
    text = " ".join(raw.decode("ascii", "replace").split())
    return text or None


def _text_at(block: bytes, offset: int) -> str | None:
    """Decode a null-terminated UTF-16LE line out of an already-read block."""
    characters = []
    limit = min(offset + MAX_SUBTITLE_BYTES, len(block) - 1)
    for position in range(offset, limit, 2):
        low, high = block[position], block[position + 1]
        if low == 0 and high == 0:
            break
        if high != 0 or not (low in (10, 13) or 32 <= low < 127):
            return None
        characters.append(chr(low))
    text = " ".join("".join(characters).split())
    return text or None


def find_subtitle_shift(pine, screen) -> int | None:
    """Find how far a screen's subtitle block has moved, by its shape.

    No line of the game's text is hardcoded here, so nothing has to be
    transcribed and nothing breaks in another language.  What is recognised
    instead is the arrangement: ten readable lines at exactly the spacing the
    recorded addresses describe.  Ten independent hits at fixed offsets is far
    more selective than any single string would be, and a wrong match would
    have to reproduce the whole layout by accident.

    Returns the offset to add to the recorded addresses, or None.
    """
    addresses = [screen.subtitles[key] for key in sorted(screen.subtitles)]
    if len(addresses) < 2:
        return None
    base = addresses[0]
    offsets = [address - base for address in addresses]
    span = offsets[-1] + MAX_SUBTITLE_BYTES

    for window in range(SUBTITLE_SEARCH_START, SUBTITLE_SEARCH_END,
                        SUBTITLE_SEARCH_STEP):
        size = SUBTITLE_SEARCH_STEP + span
        try:
            block = pine.read_aligned_range(window, size + (-size % 8))
        except Exception:
            return None
        for start in range(0, SUBTITLE_SEARCH_STEP, 2):
            first = _text_at(block, start)
            if first is None or len(first) < MIN_ANCHOR_CHARACTERS:
                continue
            if all(_text_at(block, start + offset) for offset in offsets[1:]):
                return window + start - base
    return None


def find_screen_shift(pine, screen) -> int | None:
    """Find how far a menu's own block has moved, by the game's sprite name.

    Only ever called for a screen whose *other* signature already says it is on
    screen, so the question is not "is this the main menu" -- that is settled --
    but "where has the game put it this time".

    The name must occur exactly once in the band.  It occurs three times in the
    31 MB of a main-menu capture, which is precisely why the band is a megabyte
    rather than the whole of RAM: two hits mean the band can no longer tell the
    copies apart, and choosing between them would be a guess.  The signature is
    then re-checked at the shift, so a single accidental hit still fails.

    Returns the offset to add to the recorded addresses, or None.
    """
    if screen.search_band is None:
        return None
    start, end = screen.search_band
    address, name = screen.primary.first
    overlap = len(name) - 1
    found: list[int] = []
    for window in range(start, end, SCREEN_SEARCH_STEP):
        size = min(SCREEN_SEARCH_STEP + overlap, end + overlap - window)
        try:
            block = pine.read_aligned_range(window, size + (-size % 8))
        except Exception:
            return None
        position = block.find(name)
        while position >= 0:
            hit = window + position
            # Each window is read with an overlap so a name straddling the
            # boundary is not missed, which lets the last one reach past the
            # band. A hit out there is outside what was asked for.
            if hit + len(name) <= end and hit not in found:
                found.append(hit)
                if len(found) > 1:
                    return None      # Ambiguous, so nothing is claimed.
            position = block.find(name, position + 1)
    if not found:
        return None
    shift = found[0] - address
    return shift if screen.primary.present(pine, shift) else None


SCREENS = [
    # The main menu is recognised twice over, from two allocations with
    # different lifetimes. 0x00AA15EC sits 0x344 above the cursor, so finding
    # it locates the cursor too. The five names at 0x00CF9D40-0x00CFA1C0 are
    # entries in the per-screen sprite-name table on its 0xC0 granule; they are
    # present in both main-menu captures and in no other screen's capture on
    # disk, and that block survives into Dragon Library, where 0x00AA15EC has
    # already gone. Which is the point of having it: the far signature is what
    # still answers when the near block has been torn down and rebuilt
    # somewhere else.
    Screen(
        "Main Menu", 0x00AA15EC, b"mc_menu_lineanim", 0x00AA12A8, 1,
        {0: "Dragon Adventure", 1: "Ultimate Battle Z",
         2: "Dragon Tournament", 3: "Dueling", 4: "Ultimate Training",
         5: "Evolution Z", 6: "Item Shop", 7: "Data Center", 8: "Options",
         9: "Dragon Library"},
        {0: 0x00CA9A42, 1: 0x00CA9B02, 2: 0x00CA9B82, 3: 0x00CA9C02,
         4: 0x00CA9CC2, 5: 0x00CA9D42, 6: 0x00CA9E02, 7: 0x00CA9EC2,
         8: 0x00CA9F42, 9: 0x00CA9FC2},
        # The second copy of the cursor lives in that far block too, and is
        # read for the same reason Options' and Game Level's are: a block that
        # drifts takes only its own copy with it. It reads 8 on both main-menu
        # captures, where the near cursor also reads 8, and it keeps the last
        # main-menu selection after the screen is left -- 9 on the Dragon
        # Library capture, 8 on the Options one, which are the rows those
        # screens were opened from. Three values, four captures.
        mirror=0x00CF9C34, mirror_stride=1,
        alternate=Signature([
            (0x00CF9D40, b"mc_yaji_down"),
            (0x00CF9E00, b"mc_yaji_up"),
            (0x00CFA040, b"mc_menu_off_down1"),
            (0x00CFA100, b"mc_menu_off_up1"),
            (0x00CFA1C0, b"mc_yaji"),
        ]),
        search_band=(0x00A00000, 0x00B00000),
    ),
    # The title spinner counts in twos; the main menu does not, so stride stays
    # per-screen rather than becoming a global assumption.
    Screen(
        "Title", 0x00533D60,
        bytes([0x01, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00, 0xC4, 0xE1, 0x06,
               0x53, 0x53]),
        0x00533A73, 2, {0: "New Game", 1: "Load Game"},
        # This signature also matches on the Game Level screen, where it
        # announced "New Game" over a difficulty chooser. It is a last resort.
        weak_marker=True,
    ),
    # Recognised but not mapped. Naming the screen helps; guessing at its rows
    # would not. Their markers come from a single visit each, unlike the main
    # menu's, which held across nineteen captures.
    # Options is a vertical list of five, and it wraps. Its cursor was found by
    # a press scan whose analysis matched five options and nothing else -- every
    # other menu size produced zero candidates -- then confirmed live across a
    # departure to the main menu and back, a transition it was not derived from.
    # The game keeps the same index twice: plainly at 0x00AF7294, in the block
    # Options allocates for itself beside its marker, and doubled at 0x00532173
    # in static memory. Reading both is what lets a drifting copy be noticed
    # rather than believed.
    Screen(
        "Options", 0x00AFCF85, b"mc_icon_saveload", 0x00AF7294, 1,
        {0: "Save and Load", 1: "Controller", 2: "Screen", 3: "Sound",
         4: "Exit"},
        mirror=0x00532173, mirror_stride=2,
    ),
    Screen("Dragon Library", 0x00AB1FAF, b"mc_musicprogram_0"),
    # The Game Level screen, reached after choosing a story event in Dragon
    # Adventure. Three boxes side by side reading 1, 2, and 3, arranged
    # horizontally, so it answers to Left and Right rather than Up and Down.
    # It opens on 2.
    #
    # The labels are the digits the screen actually shows. The game calls this
    # "Game Level" and the instruction line calls it the "Match level"; neither
    # says easy, normal or hard, so neither does the mod.
    #
    # Same two-copy arrangement as Options: a plain count at 0x00B054A8, beside
    # this screen's own sprite names, and the index times four at 0x00432D71 in
    # static memory. Both are read and must agree.
    #
    # The marker was 0x00B1007B, which also matches on Select Scenario: that
    # address lives in the block the two screens share byte for byte, so no
    # marker there can ever tell them apart. The same sprite name sits again at
    # 0x00D547C0, in the per-screen name table, where it is absent on all seven
    # Select Scenario captures. Verified across every capture on disk.
    #
    # F12 here used to announce an event name from 0x00D1A782 as well. That
    # address is entry 0 of a table rather than a display slot, so it said
    # "Mysterious Alien Warrior" whatever the player had actually chosen. It is
    # gone; F12 reads the instruction line the game is drawing instead, which
    # is the part that was ever true.
    Screen(
        "Game Level", 0x00D547C0, b"mc_da_5_lv_csr", 0x00B054A8, 1,
        {0: "Level 1", 1: "Level 2", 2: "Level 3"},
        {0: 0x00D179C2, 1: 0x00D179C2, 2: 0x00D179C2},
        mirror=0x00432D71, mirror_stride=4,
        in_adventure=True,
        # Not observed stale itself, but it is an entry in the same per-screen
        # table as Select Scenario's, written on the way into Dragon Adventure
        # and demonstrably not cleared on the way out. Flagged by that shared
        # mechanism rather than by its own sighting, which is weaker evidence
        # and is why this is recorded rather than assumed.
        marker_outlives_screen=True,
    ),
    # Select Scenario, the list of Dragon Adventure scenarios, reached before
    # the story events and the Game Level chooser. A vertical list that wraps.
    #
    # This screen and Game Level share their whole dynamic allocation --
    # 0x00A00000 to 0x00C00000 is identical between captures of the two, to the
    # byte -- so neither can be recognised there. Both are found instead in the
    # per-screen sprite-name table around 0x00D52000, which does differ. The
    # two markers were checked against all thirteen captures on disk and match
    # their own screen and nothing else.
    #
    # The cursor is read twice over, as everywhere here: plainly at 0x00D53625,
    # beside this screen's own marker, and again at 0x00B0536C in the other
    # allocation entirely, which is the stronger cross-check because a block
    # that drifts takes only its own copy with it.
    #
    # The labels are what the screen showed at each position, read back off the
    # screenshots rather than assumed. They are true for this save's unlock
    # state only: the list grows as scenarios are unlocked, and whether new
    # ones are appended or inserted is unknown, so a third entry could shift
    # these two. An index with no label is silent, which covers growth at the
    # end; it does not cover insertion, and that must be re-checked the first
    # time a third scenario appears.
    Screen(
        "Select Scenario", 0x00D53440, b"mc_da_2_text_off_l", 0x00D53625, 1,
        {0: "Saiyan Saga", 1: "Fateful Brothers"},
        mirror=0x00B0536C, mirror_stride=1,
        in_adventure=True,
        # **Observed still resident after Dragon Adventure was left**, on the
        # main menu and on Options, for 168 consecutive frames of the
        # 2026-09-07 17:04 session. That is what took the main menu's name
        # away and handed its option subtitles to the story reader, and it
        # announced "Select Scenario" over the Options screen besides. The
        # address is kept because it is the only one that separates this
        # screen from Game Level, and it is now outranked rather than trusted.
        marker_outlives_screen=True,
        # The one screen here whose length is not ours to know. A row we have
        # no name for means the list has grown, so say which row it is and
        # admit the name is missing -- and treat hearing this as a sign that
        # every name on this screen now needs re-checking, since an inserted
        # scenario would shift the two we do know.
        unknown_row="Scenario {position}, name not known.",
    ),
]


class MenuReader:
    """Speaks the highlighted option while the game is outside Adventure.

    Runs only when navigation guidance is suspended, so menu announcements and
    route guidance can never talk over one another.

    It also owns the boundary with the story reader.  Both read prose the game
    is drawing, and on a menu they would be reading the same line, so
    `reads_options` is the single place that decides which of them speaks --
    and the answer is always the menu, wherever the menu has an option to give.
    """

    def __init__(self, speaker, story=None):
        self.speaker = speaker
        self.screen: Screen | None = None
        # False when the screen was recognised only from a signature that says
        # nothing about where its cursor is. The screen is named; the cursor is
        # left alone until the block it lives in has been found.
        self.cursor_trusted = False
        self._spoken: str | None = None
        self._pending: int | None = None
        self._settled: int | None = None
        self._unknown_since: float | None = None
        self._announced_unknown = False
        # The story reader, so a line read out on F12 is not repeated by it a
        # moment later. Optional: the menu reader works without one.
        self._story = story
        # How far each screen's own block has moved from its recorded
        # addresses, learned by find_screen_shift and kept for the session.
        self._shifts: dict[str, int] = {}
        # None rather than 0.0: a rate limit measured against zero refuses the
        # very first search on any clock that starts near zero, which is every
        # clock in a test and some of them in the wild.
        self._last_screen_search: float | None = None
        # The screen already searched for during this visit. A search that
        # fails would otherwise repeat every twenty seconds for as long as the
        # player stayed on the screen, saying "Looking for the menu." each
        # time. Once per visit is enough; leaving and returning tries again.
        self._searched: str | None = None
        # Diagnostics already written this session, so a fault that lasts a
        # thousand frames costs the log one line rather than a thousand.
        self._noted: collections.deque = collections.deque(maxlen=NOTED_LINES)
        # Consecutive reads where a screen's two copies of the cursor
        # disagreed. One is a half-written frame; a run of them is a fault.
        self._unsettled = 0
        self._announced_unsettled = False
        self._last_disagreement: tuple[int, int] | None = None
        # How far the subtitle block has moved from the recorded addresses.
        # Zero until proven otherwise: the recorded addresses are right in the
        # run they came from, and searching costs the player a pause.
        self._subtitle_shift = 0
        self._last_subtitle_search: float | None = None
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._subtitle_down = False

    def _subtitle_pressed(self) -> bool:
        down = bool(self._user32.GetAsyncKeyState(VK_F12) & 0x8000)
        fired = down and not self._subtitle_down
        self._subtitle_down = down
        return fired and desktop_input_allowed(self._user32)

    def reads_options(self) -> bool:
        """Is the menu reader able to speak the highlighted option?

        The story reader defers to this.  Both read prose the game is drawing,
        and on a mapped menu what the game is drawing is that menu's own
        subtitle -- so leaving both running announced a subtitle for every
        option the player browsed past, and never named the option itself.

        Where this is False there is no option to prefer: an unmapped screen, a
        screen that can only name itself, a cutscene.  Reading the prose is
        then the best the mod can do, and better than silence.
        """
        return (self.screen is not None and self.screen.readable
                and self.cursor_trusted)

    def in_adventure_menu(self, pine) -> bool:
        """Is a menu showing that the HUD detector mistakes for gameplay?

        The Game Level chooser looks enough like Dragon Adventure to the pixel
        heuristic that it was classified as play, which suspended menu reading
        and left the screen silent.  The screen says what it is in memory, and
        a marker that can be checked beats a heuristic that can only be
        trusted, so the marker decides.

        Costs a short read per frame, and only for screens flagged as living
        inside Adventure -- two, at present: the Game Level chooser and the
        Select Scenario list.
        """
        for screen in SCREENS:
            if not screen.in_adventure:
                continue
            try:
                if screen.present(pine, self._shifts.get(screen.name, 0)):
                    return True
            except Exception:
                return False  # A dropped read must never suspend guidance.
        return False

    def _note_once(self, text: str) -> None:
        """Log a diagnostic, but not the same one on every frame.

        The first run of the collision note wrote the same line 168 times in
        one session, which is a log nobody will read to the end of. What
        matters is that it happened and what it said, not how many frames it
        lasted.
        """
        if text in self._noted:
            return
        self._noted.append(text)
        note(text)

    def _match(self, pine, screen) -> tuple[bool, bool]:
        """(is this screen up, does the evidence locate its cursor)."""
        shift = self._shifts.get(screen.name, 0)
        if screen.primary.present(pine, shift):
            return True, True
        if shift and screen.primary.present(pine, 0):
            # The block went back to where it was recorded, or the remembered
            # shift belonged to an allocation that has since been replaced.
            self._shifts.pop(screen.name, None)
            return True, True
        if screen.alternate is not None and screen.alternate.present(pine):
            return True, False
        return False, False

    def _detect(self, pine) -> tuple[Screen | None, bool]:
        """Identify the screen, or return None rather than guess.

        Every screen is checked, not just the first that matches. Markers were
        assumed to be mutually exclusive; the title screen's raw signature is
        not, and it shadowed the Game Level chooser -- announcing "New Game"
        over a difficulty menu, which is precisely the confident error this
        mod must never make.

        Named sprite markers decide. A raw signature is consulted only when no
        name matches, and two names matching at once means the mod does not
        know where it is and says so.

        **A marker known to outlive its screen loses to one that is not.**
        Measured, not assumed, and in both directions. The Dragon Adventure
        markers persist after the mode is left: on 2026-09-07 the log recorded
        `mc_da_2_text_off_l` still resident on the main menu and on Options,
        168 frames of it, which is what took the main menu's name away and gave
        the option subtitles to the story reader. The main menu's own names go
        the other way -- every capture of a screen inside Dragon Adventure was
        taken after the main menu had been displayed, since there is no other
        route in, and its names are absent from all eight of them.

        Returns the screen and whether its cursor may be read.
        """
        named = []
        for screen in SCREENS:
            if screen.weak_marker:
                continue
            present, trusted = self._match(pine, screen)
            if present:
                named.append((screen, trusted))

        fresh = [pair for pair in named if not pair[0].marker_outlives_screen]
        if fresh and len(fresh) < len(named):
            self._note_once(
                "menus: ignoring a marker that outlives its screen -- "
                + ", ".join(s.name for s, _ in named if s.marker_outlives_screen)
                + " while " + ", ".join(s.name for s, _ in fresh) + " is up"
            )
            named = fresh

        if len(named) == 1:
            return named[0]
        if named:
            # Written to the log, not spoken. Which screens collided is the one
            # fact that separates "the marker moved" from "a stale marker is
            # still resident", and guessing between those wasted a session --
            # then answered it in one line the first time a player hit it.
            self._note_once(
                "menus: several screens matched at once, so none was named -- "
                + ", ".join(screen.name for screen, _ in named))
            return None, False

        weak = [s for s in SCREENS if s.weak_marker and s.present(pine)]
        if len(weak) == 1:
            return weak[0], True
        return None, False

    def poll(self, pine, now: float) -> None:
        # Read the key first, and on every pass. It used to be read below the
        # point where an unrecognised screen returns early, so on any screen
        # the mod could not name -- which is every screen it has not been
        # taught -- F12 did nothing at all, not even say so.
        if self._subtitle_pressed():
            self._speak_subtitle(pine, now)

        try:
            found, trusted = self._detect(pine)
        except Exception:
            return  # A dropped read must never stop navigation guidance.

        if found is not self.screen:
            self.screen = found
            self.cursor_trusted = trusted
            self._searched = None
            self._unsettled = 0
            self._announced_unsettled = False
            self._last_disagreement = None
            self._spoken = self._settled = self._pending = None
            if found is not None:
                self._unknown_since = None
                self._announced_unknown = False
                self.speaker.say(found.name)
            else:
                # Every screen change passes through a moment where the old
                # screen has unloaded and the new one has not arrived. Saying
                # "unknown" then would interrupt on every navigation, so wait
                # to see whether it is a real unmapped screen or just a gap.
                self._unknown_since = now
            return

        self.cursor_trusted = trusted
        if self.screen is None:
            if (not self._announced_unknown and self._unknown_since is not None
                    and now - self._unknown_since >= 1.5):
                self._announced_unknown = True
                self.speaker.say("Unknown screen.")
            return

        if not trusted:
            # Named from the far signature only, so its own block has moved.
            # Looked for on the pass after the screen was announced, so the
            # player hears where they are before they hear the mod searching.
            self.cursor_trusted = self._locate_block(pine, self.screen, now)

        if not self.reads_options():
            return

        try:
            raw, label, settled = self.screen.option(
                pine, self._shifts.get(self.screen.name, 0)
            )
        except Exception:
            return
        if not settled:
            # Read again from scratch rather than committing this value.
            self._pending = None
            self._report_disagreement(pine)
            return
        self._unsettled = 0

        # Require a value to repeat before trusting it. A read can land while
        # the game is updating the cursor, and announcing that half-written
        # state would speak an option that was never displayed.
        if raw != self._pending:
            self._pending = raw
            return
        if raw == self._settled:
            return
        self._settled = raw

        if label is None:
            # Not a position this screen has a name for. Naming it anyway would
            # be the confident error this mod must never make -- but silence is
            # indistinguishable from the mod being broken, and on a list that
            # grows with progress an unnamed row is the expected result of
            # playing rather than a fault. Where the screen knows how to
            # describe such a row, say the position instead: it is honest, it
            # is checkable, and it tells the player the table needs extending.
            label = self.screen.unknown_row_label(raw)
            if label is None:
                return
        if label != self._spoken:
            self._spoken = label
            self.speaker.say(label)

    def _report_disagreement(self, pine) -> None:
        """Explain a cursor whose two copies will not agree, once.

        A single disagreement is a read landing while the game is updating,
        and answering it with silence is right.  A run of them is not: the two
        addresses have stopped meaning the same thing, and the screen then
        stays silent for as long as the player is on it with nothing to
        distinguish that from a broken mod.  Which is the fault this project
        exists to avoid, so it is said out loud.

        The two values go to the log as well.  Select Scenario's cursor was
        derived on a list of two entries, where position is only parity, so any
        counter with period two fits the press schedule as well as the real
        index does -- recorded at the time as the weakness to re-check when a
        third scenario unlocked.  If that is what this is, the log now answers
        it from ordinary play: one copy will count 0, 1, 2 and the other will
        fall back to 0.
        """
        screen = self.screen
        if screen is None or screen.mirror is None:
            return
        self._unsettled += 1
        if self._unsettled < UNSETTLED_BEFORE_SAYING:
            return
        try:
            shift = self._shifts.get(screen.name, 0)
            near = pine.read8(screen.cursor + shift)
            far = pine.read8(screen.mirror)
        except Exception:
            return
        self._note_once(
            f"menus: {screen.name} cursor copies disagree -- "
            f"0x{screen.cursor + shift:08X} reads {near} (stride "
            f"{screen.stride}), 0x{screen.mirror:08X} reads {far} (stride "
            f"{screen.mirror_stride})"
        )
        # Every distinct pair, but only once each: the sequence is the
        # evidence -- one copy counting 0, 1, 2 while the other falls back to 0
        # is a parity counter caught in the act -- and a line per frame would
        # bury it. The first run of the collision note wrote 168 identical
        # lines in one session.
        if (near, far) != self._last_disagreement:
            self._last_disagreement = (near, far)
            note(f"menus: {screen.name} disagreement, near {near} far {far}")
        if not self._announced_unsettled:
            self._announced_unsettled = True
            self.speaker.say(
                f"{screen.name}: the two copies of the cursor disagree, so "
                "the highlighted row cannot be read. F12 still reads the "
                "screen."
            )

    def _locate_block(self, pine, screen, now: float) -> bool:
        """Look for a screen's own block, when only its far name matched.

        Rate limited and announced, for the same reason the subtitle search is:
        it reads a megabyte and takes a moment, and an unexplained pause is
        indistinguishable from a crash to someone who cannot see the screen.

        Returns whether the cursor may now be read.
        """
        if screen.search_band is None or self._searched == screen.name or (
                self._last_screen_search is not None
                and now - self._last_screen_search < SCREEN_SEARCH_INTERVAL):
            return False
        self._last_screen_search = now
        self._searched = screen.name
        self.speaker.say("Looking for the menu.")
        try:
            shift = find_screen_shift(pine, screen)
        except Exception:
            shift = None
        if shift is None:
            note(f"menus: {screen.name} is up, but its own block was not found "
                 "in the search band, so its options stay silent")
            return False
        self._shifts[screen.name] = shift
        note(f"menus: {screen.name} moved by {shift:+#x}; "
             "reading its cursor there")
        return True

    def _speak_subtitle(self, pine, now: float) -> None:
        """Say the prose on screen, however it can be reached.

        Two sources, in the order of how much each claims to know.  A mapped
        screen has recorded addresses, one per row, so there the line read is
        the one belonging to the highlighted option and nothing else.
        Everything else -- an unmapped screen, a screen whose block has moved,
        a cutscene -- falls back to the pointer the game draws with, which
        reads whatever is on screen and has not moved between runs.

        Before this, F12 said "No subtitle available." on every screen without
        a recorded table, which is most of them, and was not reached at all on
        a screen the mod could not name, which is where the player most needs
        it.
        """
        line = self._recorded_subtitle(pine, now)
        if line is None:
            line = self._displayed_prose(pine)
        if line is None:
            self.speaker.say("Nothing written on screen was found.")
            return
        # The story reader would otherwise announce the same line a moment
        # later, on the screens where it is the one doing the reading.
        if self._story is not None:
            self._story.note_spoken(line)
        self.speaker.say(line)

    def _recorded_subtitle(self, pine, now: float) -> str | None:
        screen = self.screen
        if (screen is None or not screen.subtitles or not screen.readable
                or not self.cursor_trusted):
            return None
        try:
            raw = pine.read8(screen.cursor + self._shifts.get(screen.name, 0))
            address = screen.subtitles.get(raw // screen.stride)
        except Exception:
            address = None
        if address is None:
            return None
        line = self._read_line(pine, address)
        if line is None:
            # The block has moved, which happens between emulator runs. Look
            # for it once rather than leaving the recorded table dead for the
            # whole session.
            line = self._relocate_and_read(pine, screen, address, now)
        return line

    def _displayed_prose(self, pine) -> str | None:
        from .story import read_displayed
        try:
            return read_displayed(pine)
        except Exception:
            return None

    def _read_line(self, pine, address: int) -> str | None:
        try:
            return read_subtitle(pine, address + self._subtitle_shift)
        except Exception:
            return None

    def _relocate_and_read(self, pine, screen, address: int,
                           now: float) -> str | None:
        if (self._last_subtitle_search is not None
                and now - self._last_subtitle_search
                < SUBTITLE_SEARCH_INTERVAL):
            return None
        self._last_subtitle_search = now
        # The search reads a few megabytes and takes a moment. Say so, because
        # for a player who cannot see the screen an unexplained pause is
        # indistinguishable from the mod having crashed.
        self.speaker.say("Looking for the subtitles.")
        try:
            shift = find_subtitle_shift(pine, screen)
        except Exception:
            shift = None
        if shift is None:
            return None
        self._subtitle_shift = shift
        return self._read_line(pine, address)

    def suspend(self) -> None:
        """Forget the current screen so returning to it announces again."""
        self.screen = None
        self.cursor_trusted = False
        self._searched = None
        self._unsettled = 0
        self._announced_unsettled = False
        self._last_disagreement = None
        self._spoken = self._settled = self._pending = None
        self._unknown_since = None
        self._announced_unknown = False
        self._subtitle_down = False
