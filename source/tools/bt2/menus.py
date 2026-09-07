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

The subtitle addresses were recorded in one PCSX2 run and the block moves
between runs, so they are treated as a starting guess rather than a fact.  When
they stop reading as text the block is found again by its shape -- ten lines at
known spacing -- and the offset is remembered for the session.

Addresses and their evidence are recorded in docs/memory-map.md.
"""

from __future__ import annotations

import ctypes

from .hotkeys import desktop_input_allowed

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

# PCSX2 binds F1 to F6, F8 and F9. F12 is unbound, so the mod can claim it.
VK_F12 = 0x7B

# The highest row number that will ever be spoken as a bare position. A
# cursor reading beyond this is far likelier to be a bad read than a menu
# that long, and inventing a row number from garbage would be its own
# confident error.
MAX_UNNAMED_ROW = 16


class Screen:
    """A menu: how to recognise it, where its cursor is, what its rows say."""

    def __init__(self, name, marker_address, marker, cursor=None, stride=1,
                 labels=None, subtitles=None, mirror=None, mirror_stride=1,
                 context=None, in_adventure=False, weak_marker=False,
                 unknown_row=None):
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
        # Prose the game is showing about this screen -- what is being chosen,
        # rather than which option is highlighted. Read on F12, never spoken
        # automatically: it is the game's own text, but where it lives has been
        # confirmed for one story event only.
        self.context = context
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

    @property
    def readable(self) -> bool:
        return self.cursor is not None

    def present(self, pine) -> bool:
        return _read_ascii(pine, self.marker_address, len(self.marker)) == self.marker

    def option(self, pine) -> tuple[int, str | None, bool]:
        """Return the raw cursor, its label, and whether the read is settled.

        An unsettled read is one the mirrors disagreed about, which means try
        again.  That is different from a value this screen has no option for,
        where the right answer is a permanent silence.  Conflating the two
        would let one unlucky frame mute an option until the player navigated
        away and back.
        """
        raw = pine.read8(self.cursor)
        if raw % self.stride:
            return raw, None, True
        index = raw // self.stride
        if self.mirror is not None:
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


def _read_ascii(pine, address: int, count: int) -> bytes:
    return bytes(pine.read8(address + offset) for offset in range(count))


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


SCREENS = [
    Screen(
        "Main Menu", 0x00AA15EC, b"mc_menu_lineanim", 0x00AA12A8, 1,
        {0: "Dragon Adventure", 1: "Ultimate Battle Z",
         2: "Dragon Tournament", 3: "Dueling", 4: "Ultimate Training",
         5: "Evolution Z", 6: "Item Shop", 7: "Data Center", 8: "Options",
         9: "Dragon Library"},
        {0: 0x00CA9A42, 1: 0x00CA9B02, 2: 0x00CA9B82, 3: 0x00CA9C02,
         4: 0x00CA9CC2, 5: 0x00CA9D42, 6: 0x00CA9E02, 7: 0x00CA9EC2,
         8: 0x00CA9F42, 9: 0x00CA9FC2},
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
    Screen(
        "Game Level", 0x00D547C0, b"mc_da_5_lv_csr", 0x00B054A8, 1,
        {0: "Level 1", 1: "Level 2", 2: "Level 3"},
        {0: 0x00D179C2, 1: 0x00D179C2, 2: 0x00D179C2},
        mirror=0x00432D71, mirror_stride=4, context=0x00D1A782,
        in_adventure=True,
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
    """

    def __init__(self, speaker):
        self.speaker = speaker
        self.screen: Screen | None = None
        self._spoken: str | None = None
        self._pending: int | None = None
        self._settled: int | None = None
        self._unknown_since: float | None = None
        self._announced_unknown = False
        # How far the subtitle block has moved from the recorded addresses.
        # Zero until proven otherwise: the recorded addresses are right in the
        # run they came from, and searching costs the player a pause.
        self._subtitle_shift = 0
        self._last_subtitle_search = 0.0
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._subtitle_down = False

    def _subtitle_pressed(self) -> bool:
        down = bool(self._user32.GetAsyncKeyState(VK_F12) & 0x8000)
        fired = down and not self._subtitle_down
        self._subtitle_down = down
        return fired and desktop_input_allowed(self._user32)

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
                if screen.present(pine):
                    return True
            except Exception:
                return False  # A dropped read must never suspend guidance.
        return False

    def _detect(self, pine) -> Screen | None:
        """Identify the screen, or return None rather than guess.

        Every screen is checked, not just the first that matches. Markers were
        assumed to be mutually exclusive; the title screen's raw signature is
        not, and it shadowed the Game Level chooser -- announcing "New Game"
        over a difficulty menu, which is precisely the confident error this
        mod must never make.

        Named sprite markers decide. A raw signature is consulted only when no
        name matches, and two names matching at once means the mod does not
        know where it is and says so.
        """
        named = [s for s in SCREENS if not s.weak_marker and s.present(pine)]
        if len(named) == 1:
            return named[0]
        if named:
            return None
        weak = [s for s in SCREENS if s.weak_marker and s.present(pine)]
        return weak[0] if len(weak) == 1 else None

    def poll(self, pine, now: float) -> None:
        try:
            found = self._detect(pine)
        except Exception:
            return  # A dropped read must never stop navigation guidance.

        if found is not self.screen:
            self.screen = found
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

        if self.screen is None:
            if (not self._announced_unknown and self._unknown_since is not None
                    and now - self._unknown_since >= 1.5):
                self._announced_unknown = True
                self.speaker.say("Unknown screen.")
            return

        if self._subtitle_pressed():
            self._speak_subtitle(pine, now)
        if not self.screen.readable:
            return

        try:
            raw, label, settled = self.screen.option(pine)
        except Exception:
            return
        if not settled:
            # Read again from scratch rather than committing this value.
            self._pending = None
            return

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

    def _speak_subtitle(self, pine, now: float) -> None:
        screen = self.screen
        if screen is None or not screen.subtitles or not screen.readable:
            self.speaker.say("No subtitle available.")
            return
        try:
            raw = pine.read8(screen.cursor)
            address = screen.subtitles.get(raw // screen.stride)
        except Exception:
            address = None
        if address is None:
            self.speaker.say("No subtitle available.")
            return

        line = self._read_line(pine, address)
        if screen.context is not None:
            about = self._read_line(pine, screen.context)
            if about and line:
                line = f"{about}. {line}"
            elif about:
                line = about
        if line is None:
            # The block has moved, which happens between emulator runs. Look
            # for it once rather than leaving F12 dead for the whole session.
            line = self._relocate_and_read(pine, screen, address, now)
        self.speaker.say(line or "No subtitle available.")

    def _read_line(self, pine, address: int) -> str | None:
        try:
            return read_subtitle(pine, address + self._subtitle_shift)
        except Exception:
            return None

    def _relocate_and_read(self, pine, screen, address: int,
                           now: float) -> str | None:
        if now - self._last_subtitle_search < SUBTITLE_SEARCH_INTERVAL:
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
        self._spoken = self._settled = self._pending = None
        self._unknown_since = None
        self._announced_unknown = False
        self._subtitle_down = False
