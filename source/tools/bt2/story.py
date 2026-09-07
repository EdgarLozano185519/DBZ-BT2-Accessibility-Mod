"""Speak the prose the game is displaying, read from the game's own renderer.

The menu labels are artwork, so their words have to come from a table we wrote.
Prose does not: the game holds it as UTF-16LE and, at `0x008C6244`, keeps a
pointer to the string it is currently drawing.  Reading that pointer is the
whole feature.  No line of game text is hardcoded here, so nothing has to be
transcribed and nothing is tied to English.

This supersedes the ten recorded subtitle addresses in `menus.py` and the
shape-based search that relocates them when they move: those addresses came
from one PCSX2 run and the block moves between runs, while `0x008C6244` read
correctly in captures from three separate runs across two days.

**The pointer is not cleared when nothing is on screen.**  After a cutscene
ends it goes on aiming at the last thing drawn -- it has been seen pointing at
move-list text during a battle -- and on the title screen it aims at bytes that
are not text at all.  So a read is refused unless it survives every check
below, and even then only a *change* is spoken.  Announcing the last thing the
game drew, confidently, as though it were on screen is exactly the failure this
project treats as worse than silence.
"""

from __future__ import annotations

import re

# The head of a text-draw structure: a pointer to the string, then position and
# scale. Found from eight captures through one cutscene; it was the only
# address in 31 MB whose value tracked the text box.
DISPLAY_POINTER = 0x008C6244

# EE main RAM. A pointer outside this is stale or uninitialised, never text.
RAM_START = 0x00100000
RAM_END = 0x02000000

# No text box on this disc exceeds 156 characters. A run that does not
# terminate well inside this is not one of them.
MAX_TEXT_BYTES = 400
READ_BYTES = 512

# The byte order mark every string on this disc carries, in RAM as on disc.
BOM = b"\xff\xfe"

# Move lists and tutorial pages mark up their layout with a code at the start
# of a line -- "%2Charge with the triangle button", "$2Ultimate Blast". Not one
# of the 2,601 story boxes on the disc does this, so it cleanly separates the
# text the game shows a player reading a move list from the text it shows in a
# story scene. That matters because the stale pointer has been caught aiming at
# exactly this kind of text.
MARKUP = re.compile(r"(?:^|\n)[#$%]")

# General Punctuation. The only characters outside ASCII that any of the 2,601
# story boxes on this disc use are U+2019 and U+2026, and both live in here.
# The two literals below are U+2000 and U+206F and are invisible in an editor,
# so check them with a hex view rather than by eye before changing them.
PUNCTUATION_START = " "
PUNCTUATION_END = "⁯"


def _readable(text: str) -> bool:
    """Is this a line of prose rather than a coincidence of bytes?

    Printable ASCII alone is *not* the test.  Eighteen real story boxes contain
    a typographic apostrophe or an ellipsis, so an ASCII-only check would go
    quiet on "Okay, Vegeta, now it's your turn." -- the same mistake the disc
    extractor made, and the worse direction to fail in, because silence reads
    as "no line here" rather than as a fault.

    But "any printable character" is too wide, and that cost the player a
    crash: the game drew text containing U+3327, a CJK compatibility square,
    which is menu furniture rather than dialogue.  Speaking it was wrong, and
    logging it took the whole guide down.

    Every one of the 2,601 story boxes on this disc uses ASCII, newline, and
    exactly two characters outside it -- U+2019 and U+2026, both General
    Punctuation.  So that is the class accepted.  **A non-English release would
    need this widened**, which is why it is a character range rather than a
    list of words: no game text is hardcoded, only the alphabet it is written
    in.
    """
    if not text:
        return False
    for character in text:
        if character == "\n" or " " <= character <= "~":
            continue
        if PUNCTUATION_START <= character <= PUNCTUATION_END:
            continue
        return False
    return True


def read_displayed(pine) -> str | None:
    """The prose the game is drawing right now, or None if it cannot tell."""
    try:
        pointer = pine.read32(DISPLAY_POINTER)
    except Exception:
        return None
    if not RAM_START <= pointer < RAM_END - READ_BYTES:
        return None
    try:
        block = pine.read_aligned_range(pointer & ~7, READ_BYTES)
    except Exception:
        return None

    start = pointer & 7
    if block[start:start + 2] != BOM:
        return None
    raw = block[start + 2:start + 2 + MAX_TEXT_BYTES]
    end = raw.find(b"\x00\x00")
    if end < 0:
        return None                      # No terminator in range: not a string.
    if end % 2:
        end += 1
    try:
        text = raw[:end].decode("utf-16-le")
    except ValueError:
        return None
    if not _readable(text) or MARKUP.search(text):
        return None
    spoken = " ".join(text.split())
    return spoken or None


class StoryReader:
    """Speaks each line of prose as the game puts it on screen.

    Two guards, both borrowed from parts of this mod that already work.  A line
    must read the same twice running before it is spoken, which keeps a
    half-written buffer out of the player's ears exactly as the menu cursor's
    settle check does.  And only a *change* is announced, so a pointer sitting
    unchanged after a scene ends stays silent instead of repeating itself.
    """

    def __init__(self, speaker):
        self.speaker = speaker
        self._pending: str | None = None
        self._spoken: str | None = None

    def suspend(self) -> None:
        """Forget what was said, so returning to a scene re-announces it.

        **Deliberately not wired to the places `MenuReader.suspend` is.**  A
        screen should be re-announced when the player comes back to it, but a
        line of prose should not: the pointer still holds the last thing drawn
        long after the scene has ended, so forgetting it is what would let a
        stale line be announced a second time on the way into a menu.
        Remembering it is the guard, not an oversight.
        """
        self._pending = self._spoken = None

    def last_line(self) -> str | None:
        return self._spoken

    def poll(self, pine, now: float | None = None) -> str | None:
        """Read once. Returns the line spoken this pass, or None.

        Guarded the way `MenuReader.poll` is: reading prose is a convenience,
        and no failure in it may stop navigation guidance.  That is not
        theoretical -- an unencodable character in the echo took the whole
        guide down twice before the echo itself was fixed.
        """
        try:
            return self._poll(pine)
        except Exception:
            return None

    def _poll(self, pine) -> str | None:
        text = read_displayed(pine)
        if text is None:
            self._pending = None
            return None
        if text != self._pending:
            # First sighting. Wait for it to read the same again before
            # trusting it; a buffer caught mid-write reads once and never
            # twice.
            self._pending = text
            return None
        if text == self._spoken:
            return None
        self._spoken = text
        self.speaker.say(text)
        return text
