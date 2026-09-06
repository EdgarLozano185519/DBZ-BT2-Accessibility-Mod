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


class Screen:
    """A menu: how to recognise it, where its cursor is, what its rows say."""

    def __init__(self, name, marker_address, marker, cursor=None, stride=1,
                 labels=None, subtitles=None):
        self.name = name
        self.marker_address = marker_address
        self.marker = marker
        self.cursor = cursor
        self.stride = stride
        self.labels = labels or {}
        self.subtitles = subtitles or {}

    @property
    def readable(self) -> bool:
        return self.cursor is not None

    def present(self, pine) -> bool:
        return _read_ascii(pine, self.marker_address, len(self.marker)) == self.marker

    def option(self, pine) -> tuple[int, str | None]:
        raw = pine.read8(self.cursor)
        if raw % self.stride:
            return raw, None
        return raw, self.labels.get(raw // self.stride)


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
    ),
    # Recognised but not mapped. Naming the screen helps; guessing at its rows
    # would not. Their markers come from a single visit each, unlike the main
    # menu's, which held across nineteen captures.
    Screen("Options", 0x00AFCF85, b"mc_icon_saveload"),
    Screen("Dragon Library", 0x00AB1FAF, b"mc_musicprogram_0"),
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

    def _detect(self, pine) -> Screen | None:
        # Re-check the current screen first: the common case then costs one
        # short read instead of probing every screen on every poll.
        if self.screen is not None and self.screen.present(pine):
            return self.screen
        for screen in SCREENS:
            if screen is not self.screen and screen.present(pine):
                return screen
        return None

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
            raw, label = self.screen.option(pine)
        except Exception:
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
            # Not a position this screen has. Stay silent rather than name the
            # wrong option: for a player who cannot see, a confident error is
            # worse than nothing.
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
