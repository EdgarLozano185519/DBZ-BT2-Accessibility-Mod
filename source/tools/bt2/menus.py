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

**A marker that outlives its screen loses to one that does not.**  The Dragon
Adventure markers stay resident after the mode is left, which took the main
menu's name away and announced "Select Scenario" over the Options screen.  Two
named markers matching is otherwise reported as "I do not know", by design.

**A list that grows is not indexed by its rows.**  Select Scenario gains
entries as the player unlocks scenarios, and the game *inserts* them, so a row
number means something different afterwards.  The game keeps its own record of
which scenario each row is, and the names hang off that instead -- which is why
an unlock costs one unnamed row rather than all of them.

**Which of this reader and the story reader speaks** is decided here too, by
`MenuReader.reads_options`.  Both read prose the game is drawing, and on a menu
that is the menu's own subtitle, so leaving both running announced flavour text
for every option the player browsed past and never named the option.

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


class ListView:
    """A scrolling list whose visible rows the game draws through text slots.

    The Item Shop's lists work this way, measured over 55 captures on
    2026-09-08: four text-draw structures, 0x4C apart, hold the four visible
    names in list order; a row cursor counts the whole list; and a separate
    top-row byte says how far the window has scrolled.  The highlighted name
    is the slot at `row - top`.  Both counters are kept once per category tab,
    on a four-byte stride, because the game remembers the row in each tab.

    Nothing here is a table of names.  The slots point into the game's own
    item-name table, so the words are the game's and the reading is not tied
    to English.
    """

    def __init__(self, category, row_base, top_base, stride, slots,
                 categories, slot_address=None, count_base=None,
                 tab_labels=(), numbered=False):
        self.category = category
        self.row_base = row_base
        self.top_base = top_base
        self.stride = stride
        self.slots = tuple(slots)
        self.categories = categories
        # Where the game keeps the highlighted *visible* slot itself, if
        # it does. The Z Item list does, beside its tab index; it must
        # agree with row - top or the frame is not read. The shop keeps
        # no such word and reads on the two counters alone.
        self.slot_address = slot_address
        # How many rows each tab holds, one word per tab, where the game
        # keeps it. With it the row is spoken as "name, 3 of 194", so two
        # rows with the same text -- every unowned item is drawn "???" --
        # are still told apart. Without it the name alone is said.
        self.count_base = count_base
        # The tabs' names, where they are artwork and worth saying when
        # Left or Right changes the tab. Transcribed, as the main menu's
        # labels are; an index off the end says nothing.
        self.tab_labels = tuple(tab_labels)
        # Say "name, row 5" where the game keeps no count this build has
        # found -- the Item Fusion list -- so rows with the same text are
        # still told apart.
        self.numbered = numbered

    def tab_index(self, pine) -> int | None:
        category = pine.read8(self.category)
        return category if category < self.categories else None

    def tab(self, pine) -> str | None:
        index = self.tab_index(pine)
        if index is None or index >= len(self.tab_labels):
            return None
        return self.tab_labels[index]

    def line(self, pine, name: str) -> str | None:
        """The row as spoken: its name, and its place in the tab if known.

        A row at or past the tab's count is a read this build cannot
        place, and is not spoken.
        """
        if self.count_base is None and not self.numbered:
            return name
        category = self.tab_index(pine)
        if category is None:
            return None
        row = pine.read8(self.row_base + self.stride * category)
        if self.count_base is None:
            return f"{name}, row {row + 1}"
        count = pine.read32(self.count_base + self.stride * category)
        if not row < count:
            return None
        return f"{name}, {row + 1} of {count}"

    def highlighted_slot(self, pine) -> int | None:
        """The draw structure showing the highlighted row, or None."""
        category = pine.read8(self.category)
        if category >= self.categories:
            return None
        row = pine.read8(self.row_base + self.stride * category)
        top = pine.read8(self.top_base + self.stride * category)
        visible = row - top
        if not 0 <= visible < len(self.slots):
            # A row outside the window is a read mid-scroll or a layout this
            # build has not seen; naming a neighbour would be the confident
            # error, so say nothing this frame.
            return None
        if (self.slot_address is not None
                and pine.read8(self.slot_address) != visible):
            return None
        return self.slots[visible]


class DrawnRows:
    """A list is up when the game is drawing its rows where it draws them.

    The Z Item list inside Evolution Z shares its marker with the mode's
    menu and its character row, and no state byte was found that tells
    the three apart: 4,621 bytes differ between them and none in the
    mode's own allocation is clean. What is clean is the drawing. On all
    fourteen list captures the seven text structures from the display
    pointer on sit at x 66, y 170 and every 36 below, and point at item
    names; on the menu the first has moved to the dialogue box and the
    rest point at bytes that are not text, and on the character row every
    one is elsewhere. Seven positions reproduced exactly is the same
    argument a multi-name signature makes.
    """

    POSITION = 0x4

    def __init__(self, slots, x, first_y, pitch, also=()):
        self.slots = tuple(slots)
        self.x = x
        self.first_y = first_y
        self.pitch = pitch
        # Further structures that must sit at a fixed place as well: the
        # first fusion plate, drawn above the rows once an item is chosen.
        self.also = tuple(also)

    def drawn(self, pine) -> bool:
        for slot, x, y in self.also:
            if pine.read32(slot) == 0:
                return False
            position = pine.read32(slot + self.POSITION)
            if (position & 0xFFFF) != x or (position >> 16) != y:
                return False
        for index, slot in enumerate(self.slots):
            if pine.read32(slot) == 0:
                return False
            position = pine.read32(slot + self.POSITION)
            if (position & 0xFFFF) != self.x:
                return False
            if (position >> 16) != self.first_y + index * self.pitch:
                return False
        return True


class EventList:
    """Rows drawn as numbered text, with the highlighted one in a colour.

    The story event list inside Dragon Adventure, measured 2026-09-09 over
    twelve captures: the game draws through an array of text structures,
    0x4C apart, starting at the display pointer.  Each visible row is a
    number and a name, consecutive structures on the same line, and the
    highlighted row's name is painted in a colour no other row uses --
    yellow against white in the screenshots.  Each structure carries its
    position at +4 and its colour at +0x18, and the game hides text by
    zeroing the colour's alpha or moving it below the bottom of the screen,
    which is how a stale row and an off-screen line are told from a drawn
    one.  The shop paints every row alike and marks its highlight with a
    cursor sprite, which is why it needs a row counter and this does not.

    The structures are scanned rather than fixed, because the game inserts
    one at the front of the array while it asks which event to start from,
    and a fixed layout then read a number as a name and named the wrong
    thing.  A row is a pair the text itself vouches for: digits, then not.

    **Two readings must agree.**  The colour names a row; the game's own row
    counter, less the window's top row, names a structure; the row is
    spoken only when they are the same one.  The counter alone was found by
    fitting eight cued presses, so it is the colour's cross-check and not a
    replacement for it.  Any other pattern -- two rows apart, all alike, a
    counter off the window -- is a frame this build has not seen, and it
    says nothing rather than pick.

    Nothing here is a table of names.  The structures point into the game's
    own event-name table, so the words are the game's and the reading is not
    tied to English -- and the number is spoken as the screen writes it.
    """

    COLOUR = 0x18
    POSITION = 0x4

    def __init__(self, base, stride, count, row=None, top=None,
                 per=None, per_stride=4, screen_height=448):
        self.base = base
        self.stride = stride
        self.count = count
        # The game's own row counter and window top, or None where a single
        # visible row is the whole reading, as on Game Level's heading.
        # Both are kept once per scenario, on a four-byte stride, indexed by
        # the scenario list's own cursor: `per` is that cursor's address.
        self.row = row
        self.top = top
        self.per = per
        self.per_stride = per_stride
        self.screen_height = screen_height

    def counters(self, pine) -> tuple[int, int]:
        """(row, window top) for the scenario whose list is showing."""
        offset = 0 if self.per is None else self.per_stride * pine.read8(self.per)
        return pine.read8(self.row + offset), pine.read8(self.top + offset)

    def visible(self, pine, address: int) -> bool:
        """Is this structure drawn where the player can see it?

        Three ways the game hides text, each seen: alpha zero (stale rows
        under Game Level), a y below the bottom edge (the parked line), and
        an x off the left edge -- Game Level's heading pair, still yellow
        and still at full alpha, sits at x = -412 once the list is back.
        Positions are signed halfwords.
        """
        if pine.read32(address) == 0:
            return False
        if (pine.read32(address + self.COLOUR) >> 24) == 0:
            return False
        position = pine.read32(address + self.POSITION)
        x = position & 0xFFFF
        y = position >> 16
        if x >= 0x8000 or y >= 0x8000:
            return False
        return y < self.screen_height

    def rows(self, pine) -> list[tuple[int, int, str, str]]:
        """(number structure, name structure, number, name), in order."""
        from . import story
        found = []
        previous = None
        for index in range(self.count):
            address = self.base + index * self.stride
            if not self.visible(pine, address):
                previous = None
                continue
            text = story.displayed(pine, address)[0]
            line = pine.read32(address + self.POSITION) >> 16
            if previous is not None and text and not text.isdigit():
                number_at, number, number_line = previous
                # A name sits a pixel below its number on most rows, and
                # nine above it when it wraps onto two lines ("The Terrible
                # Super Namekian!", Lord Slug). Rows are 48 apart.
                if abs(number_line - line) <= 16:
                    found.append((number_at, address, number, text))
                    previous = None
                    continue
            previous = (address, text, line) if text and text.isdigit() else None
        return found

    def highlighted(self, pine) -> tuple[int, int, str, str] | None:
        """The highlighted row, or None when the readings do not agree.

        Three or more rows: the one whose name colour no other row shares,
        while every other row agrees, and the counter must name the same
        one.  Two rows: the colour can only say that they differ -- either
        is the odd one out -- so the counter chooses, and the chosen row
        must also be the one drawn a step to the left, which the highlight
        always is (x 41 and 75 against 43 and 76 on every capture).  One
        row: itself, if the counter says 0.
        """
        rows = self.rows(pine)
        if not rows:
            return None
        colours = [pine.read32(name + self.COLOUR) for _, name, _, _ in rows]
        by_colour = None
        if len(rows) == 1:
            by_colour = rows[0]
        elif len(rows) >= 3:
            odd = [row for row, colour in zip(rows, colours)
                   if colours.count(colour) == 1]
            rest = {colour for colour in colours if colours.count(colour) != 1}
            if len(odd) != 1 or len(rest) != 1:
                return None
            by_colour = odd[0]
        elif colours[0] == colours[1]:
            return None
        if self.row is None:
            return by_colour
        row, top = self.counters(pine)
        index = row - top
        if not 0 <= index < len(rows):
            return None
        chosen = rows[index]
        if by_colour is not None:
            return chosen if chosen is by_colour else None
        other = rows[1 - index]
        left = pine.read32(chosen[1] + self.POSITION) & 0xFFFF
        right = pine.read32(other[1] + self.POSITION) & 0xFFFF
        return chosen if left < right else None

    def label(self, pine) -> str | None:
        """The highlighted row as the screen writes it, number then name."""
        row = self.highlighted(pine)
        if row is None:
            return None
        _, _, number, name = row
        return f"{number} {name}"

    def prompt(self, pine) -> str | None:
        """The first structure's text, when it is on screen.

        On the event list that is a line parked below the screen's bottom
        edge, and never read.  While the game asks which event to start
        from -- the state it opens in from Select Scenario -- it is that
        question, drawn where the synopsis was, and no row is highlighted.
        """
        from . import story
        if not self.visible(pine, self.base):
            return None
        return story.displayed(pine, self.base)[0]

    def spoken(self, pine) -> str | None:
        return self.label(pine) or self.prompt(pine)


class TextAt:
    """One text structure, spoken with a prefix, as a screen's heading."""

    def __init__(self, slot, prefix):
        self.slot = slot
        self.prefix = prefix

    def label(self, pine) -> str | None:
        from . import story
        text = story.displayed(pine, self.slot)[0]
        return None if text is None else f"{self.prefix}{text}"


class ExplanationView:
    """The Explanation box behind Square: an item's name and three headed lines.

    Measured 2026-09-09 on the Item Fusion list (`ifuse0`, `ifuse11`): the
    game moves the first text structure to the box's title bar, draws the
    three headings -- "<Benefit>", "<Available Location>", "<Available
    Character>" -- through the next three, and the three answers through
    the three after that, all at fixed positions.  Closed, the title
    structure goes back to the list and the answers stay resident with
    their alpha zeroed, so the box is up when the title is where the box
    draws it, the headings are where they belong, and the answers are
    visible.  Square or Triangle closes it.  Every word is the game's.
    """

    POSITION = 0x4
    COLOUR = 0x18

    def __init__(self, title, pairs, positions):
        self.title = title
        self.pairs = tuple(pairs)
        self.positions = dict(positions)

    def drawn(self, pine) -> bool:
        for slot, (x, y) in self.positions.items():
            if pine.read32(slot) == 0:
                return False
            position = pine.read32(slot + self.POSITION)
            if (position & 0xFFFF) != x or (position >> 16) != y:
                return False
        for _, value in self.pairs:
            if (pine.read32(value + self.COLOUR) >> 24) == 0:
                return False
        return True

    def label(self, pine) -> str | None:
        from . import story
        title = story.displayed(pine, self.title)[0]
        if title is None:
            return None
        parts = [title]
        for heading, value in self.pairs:
            head = story.displayed(pine, heading)[0]
            text = story.displayed(pine, value)[0]
            if head is None or text is None:
                return None
            parts.append(f"{head.strip('<>')}, {text}")
        return ". ".join(parts) + "."


class QuantityView:
    """A how-many picker: one number the player raises and lowers.

    The Item Shop's, measured 2026-09-08 over a cued run of fourteen presses:
    Up adds one, Down takes one and stops at one, Right jumps to the most the
    player can afford, Left jumps back to one.  The number is spoken as the
    screen shows it -- "times 2" for the box that reads x002.  The Zeni the
    screen shows beside it, what would be left after buying, is not spoken:
    no word in RAM holds the price, the total or that balance, so it cannot
    be computed honestly.
    """

    def __init__(self, quantity):
        self.quantity = quantity

    def label(self, pine) -> str | None:
        quantity = pine.read8(self.quantity)
        if quantity == 0:
            return None      # The picker is not up, whatever the state says.
        return f"times {quantity}"


class Screen:
    """A menu: how to recognise it, where its cursor is, what its rows say."""

    def __init__(self, name, marker_address, marker, cursor=None, stride=1,
                 labels=None, subtitles=None, mirror=None, mirror_stride=1,
                 in_adventure=False, weak_marker=False, unknown_row=None,
                 alternate=None, search_band=None,
                 marker_outlives_screen=False, count_address=None,
                 unknown_row_with_count=None, id_array=None, id_stride=4,
                 labels_by_id=None, name_pointers=(), list_view=None,
                 quantity_view=None, state_address=None, variants=(),
                 state_value=None, event_list=None, prose_pointers=(),
                 heading=None, drawn_variants=(), text_labels=None,
                 arrival_slots=1, explanation_view=None):
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
        # The same, for a list whose length the game will tell us.
        self.unknown_row_with_count = unknown_row_with_count
        # Where the game keeps how many rows this list has.
        self.count_address = count_address
        # An array of *which* item each row is, in the order the rows appear.
        # A list that grows with the player's progress needs this: the row
        # number means something different after every unlock, and the game's
        # own answer to "what is this row" does not.
        self.id_array = id_array
        self.id_stride = id_stride
        # Names keyed by that answer rather than by row, so they survive.
        self.labels_by_id = labels_by_id or {}
        # Where the highlighted entry's name is read from the text the game
        # is drawing rather than from a cursor and a table of labels: a tuple
        # of (pointer address, spoken prefix or None), one per slot the screen
        # draws. The character select is the one screen so far: its names are
        # in the game's own table, the first pointer followed player 1's
        # highlight through every capture taken, and no cursor was needed.
        # Nothing is transcribed and nothing is tied to English. The prefix is
        # said the first time a different slot changes, so a player who has
        # moved from one panel to the other hears which one is speaking.
        self.name_pointers = tuple(name_pointers)
        # A scrolling list read through the game's text-draw slots -- see
        # ListView. The Item Shop's Buy and Sell lists are the two so far.
        self.list_view = list_view
        # A number the player picks; see QuantityView.
        self.quantity_view = quantity_view
        # A screen that is really several: the Item Shop keeps one marker up
        # through its Buy/Sell menu and both item lists, and tells them apart
        # by a state byte. `variants` maps that byte's value to the screen it
        # means; each variant answers to the same marker plus its own value.
        # A value with no variant leaves the base screen up, named but
        # unreadable, so the player hears where they are and nothing invented
        # -- and the guide's Adventure gate still sees the marker, so world-map
        # guidance cannot resume over a shop dialog it does not know.
        self.state_address = state_address
        # A screen may also demand a value there itself, without variants.
        # The three Dragon Adventure screens share one allocation and one
        # per-screen sprite table, so their markers cannot tell them apart
        # on their own; the byte at 0x00B054B0 can, and each of them names
        # the value it needs. A marker with the wrong value is not a match.
        self.state_value = state_value
        self.variants = tuple(variants)
        # Variants told apart by the drawing rather than a state byte: a
        # tuple of (DrawnRows, Screen). The first whose rows are drawn is
        # the screen; none drawn leaves the base screen up, still
        # readable, since its own pointer is what the game draws there.
        self.drawn_variants = tuple(drawn_variants)
        # Names for entries whose labels are artwork, keyed by the text the
        # game draws beside them -- the highlighted entry's subtitle on the
        # Evolution Z menu. No cursor is read: the game's own line picks
        # the name, and a line not in the table is spoken bare, as before.
        self.text_labels = text_labels or {}
        # How many of the spoken slots are said when the screen arrives.
        # One, ordinarily -- player 1 on the character select. The Z Item
        # list says its tab and then its row, so two.
        self.arrival_slots = arrival_slots
        # The Explanation box, read whole; see ExplanationView.
        self.explanation_view = explanation_view
        # A list whose highlight is a colour rather than a counter; see
        # EventList. The story event list is the one so far.
        self.event_list = event_list
        # Where F12 reads on this screen, when the game's display pointer
        # may aim at something other than the prose the player can see:
        # text structures, in order of preference, of which the first one
        # drawn on screen is read. The story event list parks a line below
        # the bottom edge in the first and draws its synopsis in the second,
        # except while it is asking which event to start from, when the
        # question is in the first and on screen.
        self.prose_pointers = tuple(prose_pointers)
        # Text the screen draws once at the top and never moves -- Game
        # Level's event number and name -- said after the screen's name on
        # arrival. An EventList with no counter; see announcement().
        self.heading = heading
        for value, variant in self.variants:
            variant.state_address = state_address
            variant.state_value = value
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

    def announcement(self, pine) -> str:
        """What to say on arrival: the screen's name, and its heading if drawn."""
        if self.heading is None:
            return self.name
        try:
            line = self.heading.label(pine)
        except Exception:
            line = None
        return self.name if line is None else f"{self.name}. {line}"

    @property
    def readable(self) -> bool:
        return self.cursor is not None or self.speaks_names

    @property
    def speaks_names(self) -> bool:
        """Does this screen read the game's drawn text rather than a table?"""
        return (bool(self.name_pointers) or self.list_view is not None
                or self.quantity_view is not None
                or self.event_list is not None
                or self.explanation_view is not None)

    @property
    def name_prefixes(self) -> tuple[str | None, ...]:
        prefixes = tuple(prefix for _, prefix in self.name_pointers)
        if self.list_view is not None and self.list_view.tab_labels:
            return (None, None) + prefixes
        if (self.list_view is not None or self.quantity_view is not None
                or self.event_list is not None
                or self.explanation_view is not None):
            return (None,) + prefixes
        return prefixes

    def displayed_names(self, pine) -> tuple[str | None, ...]:
        """What each spoken slot says now, or None where it says nothing.

        The first slot is the list's highlighted row or the picker's number
        where the screen has one; the draw pointers follow.  On the shop's
        lists the display pointer is the second slot, so Baba's line is
        spoken when it *changes* while the list is up -- the not-enough-money
        refusal happens there, in the list, with nothing else moving -- and
        not on arrival, when the first slot alone is said.
        """
        from . import story
        names = []
        if self.list_view is not None:
            if self.list_view.tab_labels:
                names.append(self.list_view.tab(pine))
            slot = self.list_view.highlighted_slot(pine)
            name = None if slot is None else story.displayed(pine, slot)[0]
            names.append(None if name is None
                         else self.list_view.line(pine, name))
        elif self.quantity_view is not None:
            names.append(self.quantity_view.label(pine))
        elif self.event_list is not None:
            names.append(self.event_list.spoken(pine))
        elif self.explanation_view is not None:
            names.append(self.explanation_view.label(pine))
        for address, _ in self.name_pointers:
            text = story.displayed(pine, address)[0]
            label = self.text_labels.get(text)
            names.append(text if label is None else f"{label}. {text}")
        return tuple(names)

    def state(self, pine) -> int | None:
        if self.state_address is None:
            return None
        return pine.read8(self.state_address)

    def resolve(self, pine):
        """The variant the state byte names, the screen itself, or None."""
        for rows, variant in self.drawn_variants:
            try:
                if rows.drawn(pine):
                    return variant
            except Exception:
                return None
        if not self.variants:
            return self
        value = self.state(pine)
        for wanted, variant in self.variants:
            if value == wanted:
                return variant
        return None

    def present(self, pine, shift: int = 0) -> bool:
        if self.state_value is not None and self.state(pine) != self.state_value:
            return False
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
        if self.count_address is not None:
            count = pine.read8(self.count_address)
            if not 1 <= count <= MAX_UNNAMED_ROW:
                # The screen is still loading, or this is a bad read. Either
                # way it is not an answer, so ask again rather than name a row
                # from a list that may not be there yet.
                return raw, None, False
            if index >= count:
                return raw, None, False
            if self.id_array is not None:
                # Ask the game which scenario this row *is*, rather than
                # assuming the row number means the same thing it did before
                # the player unlocked something.
                which = pine.read8(self.id_array + index * self.id_stride)
                return raw, self.labels_by_id.get(which), True
        return raw, self.labels.get(index), True

    def entry_count(self, pine) -> int | None:
        """How many rows the game says this list has, or None if unknown."""
        if self.count_address is None:
            return None
        try:
            count = pine.read8(self.count_address)
        except Exception:
            return None
        return count if 1 <= count <= MAX_UNNAMED_ROW else None

    def scenario_ids(self, pine) -> list[int] | None:
        """Which scenarios this list is showing, in the order it shows them.

        Diagnostic and test use; `option` reads the single entry it needs.
        """
        if self.id_array is None:
            return None
        count = self.entry_count(pine)
        if count is None:
            return None
        try:
            return [pine.read8(self.id_array + n * self.id_stride)
                    for n in range(count)]
        except Exception:
            return None

    def unknown_row_label(self, raw: int, count: int | None = None) -> str | None:
        """Describe a row with no name, or return None to stay silent."""
        if self.unknown_row is None:
            return None
        if self.stride and raw % self.stride:
            return None          # Not a whole index; this is a bad read.
        index = raw // self.stride
        if index > MAX_UNNAMED_ROW:
            return None
        if count and self.unknown_row_with_count is not None:
            return self.unknown_row_with_count.format(position=index + 1,
                                                      count=count)
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


# The Item Shop's lists; see the Item Shop entry below.
# The Z Item list inside Evolution Z, from the cued walk of 2026-09-09
# (`zlist0`-`zlist13`, plus `fusion1`): seven visible rows in the first
# seven text structures, a row counter per tab at 0x00B43A70 with the tab
# index after the five of them, the window top per tab at 0x00B467F4, and
# the game's own visible-slot word at 0x00B43A8C, which must agree. The
# five item counts follow at 0x00B43AA4 (155, 105, 60, 194, 7 on this
# save), the only five-word array in RAM that is constant across the walk
# and ends in the Dragon Ball tab's seven, with the scrollbar thumbs to
# match. Every unowned item is drawn "???", so the row is said with its
# place: "???, 3 of 194". The tab names are artwork, transcribed.
ZITEM_LIST = ListView(
    category=0x00B43A84, row_base=0x00B43A70, top_base=0x00B467F4, stride=4,
    slots=tuple(0x008C6244 + 0x4C * index for index in range(7)),
    categories=5, slot_address=0x00B43A8C, count_base=0x00B43AA4,
    tab_labels=("Ability Type", "Support Type", "Fusion type",
                "Secret Type", "Dragon Ball"))
ZITEM_ROWS = DrawnRows(ZITEM_LIST.slots, x=66, first_y=170, pitch=36)

# The Item Fusion list, from the cued walk of 2026-09-09 (`ifuse0`-
# `ifuse13`): four visible rows in the first four text structures, the
# same block shape as the catalog's in a block of its own -- tab index at
# 0x00B43B18, a row per tab from 0x00B43B1C, a window top per tab from
# 0x00B43B2C, four tabs. No per-tab count was found (the pair 38, 20 the
# scrollbars predict occurs only inside unrelated tables), so rows are
# numbered. The word at 0x00B43B14 reads 32 while the Explanation box is
# open and 0 otherwise; the box is recognised by its drawing instead, so
# the same reader serves the catalog, where that word was never seen.
ZFUSE_LIST = ListView(
    category=0x00B43B18, row_base=0x00B43B1C, top_base=0x00B43B2C, stride=4,
    slots=tuple(0x008C6244 + 0x4C * index for index in range(4)),
    categories=4, numbered=True,
    tab_labels=("Ability Type", "Support Type", "Fusion type",
                "Secret Type"))
ZFUSE_ROWS = DrawnRows(ZFUSE_LIST.slots, x=66, first_y=278, pitch=36)

# After Cross on an owned item (`fuse0`-`fuse6`, 2026-09-09, late): the
# game inserts a structure at the front for the first plate, at (66, 151)
# with the item's name, and the four rows move to the four structures
# after it, same positions. The counters do not move. One copy of the
# item leaves the row's count for the plate; Triangle gives it back.
# Cross on a row the player owns none of changes nothing, twice over.
# The second plate has not been seen: no second owned item was chosen.
ZFUSE_LIST_CHOSEN = ListView(
    category=0x00B43B18, row_base=0x00B43B1C, top_base=0x00B43B2C, stride=4,
    slots=tuple(0x008C6244 + 0x4C * index for index in range(1, 5)),
    categories=4, numbered=True, tab_labels=ZFUSE_LIST.tab_labels)
ZFUSE_ROWS_CHOSEN = DrawnRows(ZFUSE_LIST_CHOSEN.slots, x=66, first_y=278,
                              pitch=36, also=((0x008C6244, 66, 151),))
ZFUSE_PLATE = TextAt(0x008C6244, "First item: ")

# The Explanation box behind Square, measured on the Item Fusion list.
_SLOT = [0x008C6244 + 0x4C * index for index in range(7)]
EXPLANATION = ExplanationView(
    title=_SLOT[0],
    pairs=((_SLOT[1], _SLOT[4]), (_SLOT[2], _SLOT[5]), (_SLOT[3], _SLOT[6])),
    positions={_SLOT[0]: (256, 44), _SLOT[1]: (54, 86),
               _SLOT[2]: (54, 206), _SLOT[3]: (54, 288)})

SHOP_LIST = ListView(
    category=0x008CD360, row_base=0x008CC330, top_base=0x008CC340, stride=4,
    slots=(0x008C6290, 0x008C62DC, 0x008C6328, 0x008C6374), categories=4)

# The story event list's rows, in the same text-draw structures the shop
# uses, from the second pair on: the first structure holds a line drawn off
# the bottom of the screen and the second the synopsis. See EventList and
# the Story Events entry below.
EVENT_LIST = EventList(
    base=0x008C6244, stride=0x4C, count=20,
    # The row counter and the window's top row, in the Dragon Adventure
    # block beside the scenario list's cursor: the one address each that
    # fitted eight cued presses on the Saiyan Saga (rows 1, 2, 1, 2, 3, 4,
    # 5, 6; tops 0 to 2), and both read 0 on the earlier capture at row 0
    # they were not fitted to. **They are kept once per scenario**: on Tree
    # of Might, the second row of the scenario list, the list opened on its
    # row 01 with 0x00B05378 reading 0 and 0x00B0537C reading 1 -- the
    # guide was silent on it in play for exactly that reason, 2026-09-09,
    # `tree_a` -- so the scenario cursor at 0x00B0536C picks the slot.
    row=0x00B05378, top=0x00B05440, per=0x00B0536C)

# Game Level draws the chosen event's number and name once at the top, in
# the same array, at whichever index is free: 4 and 5 on one capture, 12
# and 13 on another. The stale rows beneath keep their text with alpha
# zero, so the one visible pair is the heading.
EVENT_HEADING = EventList(base=0x008C6244, stride=0x4C, count=20)

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
        # announced "New Game" over a difficulty chooser, and on both
        # character selects, one of them intermittently. It is a last resort,
        # and since 2026-09-08 it is also refused whenever the game is drawing
        # text -- see MenuReader._text_on_screen.
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
    # The Item Shop, Baba's shop off the main menu: a two-entry menu, Buy Z
    # Item above Sell Z Item, and behind each a scrolling list of Z-items in
    # four category tabs. One marker stays up through all of it -- the
    # highlighted item-category icon sprite, in the block the shop allocates
    # for itself at 0x00983D32-0x00989BF9 -- and a state byte at 0x008CD36C
    # says which part is showing: 0 on the menu, 8 in the Buy list, 0x18 in
    # the Sell list, on every one of the 56 captures taken 2026-09-08. Its
    # upper bytes vary with the route in and are ignored.
    #
    # The marker is in no other capture on disk, and no other screen's fresh
    # marker matches here -- only Select Scenario's stale one, which this
    # outranks. Before this entry the guide announced "Select Scenario" over
    # the shop, by that stale marker; the 2026-09-08 21:55 log has it.
    #
    # `in_adventure` because the HUD heuristic calls the shop gameplay
    # (measured on its screenshots). The base screen carries the flag on the
    # marker alone, so a shop dialog this build has not mapped -- the
    # purchase confirmation, say -- keeps world-map guidance off.
    #
    # The Buy/Sell cursor is kept twice, as on Options and Game Level: plainly
    # at 0x008CC32C in the shop's low block and doubled at 0x00532943 in static
    # memory, agreeing on all ten captures of the menu, including after a
    # return from each list -- the transition it was not derived from. Off
    # the menu the static copy is reused and the two disagree, which is why
    # the cursor belongs to the menu variant and not the base screen.
    #
    # The lists draw their four visible names through text-draw slots -- the
    # display pointer's structure and the three after it, 0x4C apart -- in
    # list order, with no highlight flag. The row cursor counts the whole
    # list and a top-row byte counts the scroll; both are per category tab,
    # four bytes apart, and the category index is at 0x008CD360. `row - top`
    # picked the highlighted name on every one of 41 list captures read back
    # against its screenshot: nine rows of one tab in both directions, the end
    # of the list (it does not wrap), and three other tabs. The top-row array
    # is measured for the first tab only; the others never scrolled.
    #
    # Nothing is transcribed for the lists: the item names are the game's
    # own table, read through the slots. Prices are sprite digits and are
    # not read. Baba's line beneath everything is prose, read on F12.
    #
    # Cross on an affordable item puts the state byte at 0x28: a how-many
    # picker. The list stays drawn, the bottom bar reads Decide and Return,
    # the count box shows the quantity and the Zeni display what would be
    # left. The quantity is at 0x008CD364, beside the category index: 1 on
    # entry, Up and Down by one with a floor of one, Right to the most
    # affordable, Left back to one -- fourteen cued presses on 2026-09-08,
    # each read off its screenshot, and 0 whenever the picker is not up.
    # **Baba's box does not change on this screen**: it keeps her last line,
    # which was "Hey, you don't have enough money!!" on every capture, so it
    # is deliberately not read here. An earlier build spoke it, from a
    # log-only mapping, and was wrong.
    #
    # Cross on an item the player cannot afford does **not** enter the
    # picker: the state stays 0x08, the list, and only Baba's line changes.
    # So the list variants read the display pointer as a second slot, spoken
    # on change -- the refusal is heard, the prompt on arrival is not.
    #
    # What Cross does in the picker -- a further question, or the sale --
    # has not been seen; nothing has been bought. That state will be logged
    # by value when it happens, like this one was.
    Screen(
        "Item Shop", 0x00984118, b"mc_item_category_icon_on",
        in_adventure=True,
        state_address=0x008CD36C,
        variants=(
            (0x00, Screen(
                "Item Shop", 0x00984118, b"mc_item_category_icon_on",
                0x008CC32C, 1, {0: "Buy Z Item", 1: "Sell Z Item"},
                mirror=0x00532943, mirror_stride=2, in_adventure=True)),
            (0x08, Screen(
                "Buy Z Item", 0x00984118, b"mc_item_category_icon_on",
                in_adventure=True, list_view=SHOP_LIST,
                name_pointers=((0x008C6244, None),))),
            (0x18, Screen(
                "Sell Z Item", 0x00984118, b"mc_item_category_icon_on",
                in_adventure=True, list_view=SHOP_LIST,
                name_pointers=((0x008C6244, None),))),
            (0x28, Screen(
                "How many", 0x00984118, b"mc_item_category_icon_on",
                in_adventure=True, quantity_view=QuantityView(0x008CD364))),
        ),
    ),
    # The two-player character select, reached from the battle modes. Two
    # horizontal rows of portraits, player 1 above and player 2 below, with
    # each player's highlighted name drawn as text between them.
    #
    # Added 2026-09-08. The marker is the scroll arrow sprite this screen
    # loads into the dynamic region; the name occurs in no other capture on
    # disk, and the reverse holds too -- no other screen's named marker matches
    # here, only the title screen's raw signature, which this named marker
    # outranks. Before this entry the mod announced "New Game" over the
    # character grid.
    #
    # There is no cursor address, and none is needed. The names the screen
    # shows are in the game's own table -- 135 UTF-16 entries on a 0x40 stride,
    # at 0x00D61C00 in these captures -- and the pointer at story.DISPLAY_POINTER
    # aimed at player 1's highlighted name in all eight captures: one taken
    # before the cued scan and seven during it, across both axes of the grid,
    # each checked against its screenshot. A search for the highlighted index
    # itself found no byte-sized ramp in those captures, and did not need to.
    #
    # Player 2's name is drawn by a second structure of the same shape, 0x98
    # bytes after the first. The first pointer stayed on Goku after player 1
    # had confirmed and the cursor had moved to the lower row, which is why
    # player 2's row was silent in play on 2026-09-08: it never follows
    # player 2. The second was found from captures in which player 2 had
    # never moved, and then verified on a second cued scan of seven presses
    # across both axes of player 2's grid -- Teen Gohan, Gohan, Teen Gohan,
    # Chiaotzu, Trunks (Sword), Piccolo, Gohan, each read off its screenshot
    # -- while the first stayed on Goku throughout. Whether this marker
    # survives leaving the screen is unmeasured; no capture was taken by that
    # route.
    Screen("Character Select", 0x009CE8D4, b"mc_chara_select_yazurushi_up",
           name_pointers=((0x008C6244, None), (0x008C62DC, "Player 2"))),
    # Dragon Tournament's entry screen, added 2026-09-08 after it was silent
    # in play: the same strip of portraits along the top, one name panel, and
    # a grid of eight entrant slots. The game loads the same arrow sprite but
    # at a different address in this mode, 0xA37E above Dueling's, so the
    # Dueling marker does not match here and this one does not match there --
    # checked across all 44 captures on disk. One visit only, so far.
    #
    # One name pointer, not two: the second draw slot holds unrelated menu
    # text here ("Return to Character Select" in the capture), and reading it
    # would have announced that as a player 2 who does not exist. Before this
    # entry the mod flickered between "Unknown screen" and "New Game" on this
    # grid; see the weak-marker rule in MenuReader._detect for the second
    # half of that.
    Screen("Tournament Character Select", 0x009D8C52,
           b"mc_chara_select_yazurushi_up",
           name_pointers=((0x008C6244, None),)),
    # Evolution Z, added 2026-09-09: the same arrow sprite the two
    # character selects use, at a third address -- checked against every
    # capture on disk, present in this mode only, and neither of the other
    # two addresses matches here. The marker holds through the whole mode:
    # its three-entry menu (Z Item Collection, Z Item List, Item Fusion,
    # artwork all, with King Kai's line and the highlighted entry's
    # subtitle as text), a character row with the highlighted name drawn
    # beneath seven portraits, and the Z Item list. The base screen reads
    # the first draw slot, which is the character's name on the row and
    # the subtitle on the menu -- what the game draws there. The list is
    # a variant told apart by its drawing; see DrawnRows. Heard in play
    # the same day on the row and the menu; the list is from the walk.
    #
    # The menu's entries are named from their subtitles, which are the
    # game's text: "This is a catalog..." was followed by the Z Item list
    # in the 18:06 log and "You can create Z-items with Item Fusion." by
    # an item screen in the 21:34 one, each on a Cross; the third is the
    # remaining entry. A subtitle not in the table is spoken bare.
    Screen("Evolution Z", 0x00A5FF93, b"mc_chara_select_yazurushi_up",
           name_pointers=((0x008C6244, None),),
           text_labels={
               "You can replace Z-items!": "Z Item Collection",
               "This is a catalog of the Z-items you have.": "Z Item List",
               "You can create Z-items with Item Fusion.": "Item Fusion"},
           drawn_variants=(
               (EXPLANATION, Screen(
                   "Explanation", 0x00A5FF93,
                   b"mc_chara_select_yazurushi_up",
                   explanation_view=EXPLANATION)),
               (ZITEM_ROWS, Screen(
                   "Z Item List", 0x00A5FF93,
                   b"mc_chara_select_yazurushi_up",
                   list_view=ZITEM_LIST, arrival_slots=2)),
               (ZFUSE_ROWS, Screen(
                   "Z Item Fusion", 0x00A5FF93,
                   b"mc_chara_select_yazurushi_up",
                   list_view=ZFUSE_LIST, arrival_slots=2)),
               (ZFUSE_ROWS_CHOSEN, Screen(
                   "Z Item Fusion", 0x00A5FF93,
                   b"mc_chara_select_yazurushi_up",
                   list_view=ZFUSE_LIST_CHOSEN, arrival_slots=2,
                   heading=ZFUSE_PLATE)))),
    # The story event list, between Select Scenario and Game Level: the
    # events of the chosen scenario, five to a window, each numbered, with
    # the highlighted one's synopsis in a box below. Mapped 2026-09-09 from
    # one capture, `event_a`, on the first event of the Saiyan Saga.
    #
    # It shares Select Scenario's marker and allocation -- 0x00D53440 is the
    # same bytes on both -- and is told apart by the Dragon Adventure menu
    # byte at 0x00B054B0, which reads 1 here, 0 on the scenario list and 2 on
    # Game Level. A second byte, 0x00B052F4, agrees (0x18, 0, 8). Neither
    # screen can be named without its value, so neither is.
    #
    # The game draws the visible rows through the text structures the
    # shop's lists use and paints the highlighted row's name in a colour the
    # others do not share; its own row counter at 0x00B05378, less the
    # window top at 0x00B05440, must name the same row. EventList reads
    # both. The names come from the game's own event table through those
    # pointers, so nothing was transcribed. Verified on a cued walk of
    # eleven presses the same day: eight rows, a scrolled window, Triangle
    # back to Select Scenario, Cross back in and Cross on to Game Level,
    # each capture matched against its screenshot.
    #
    # Coming back in from Select Scenario the game first asks "Which story
    # event will you start your adventure from?", with no row highlighted
    # and the array shifted by one; that question is spoken instead of a
    # row, and the row once a key moves it.
    #
    # The marker outlives its screen exactly as Select Scenario's does -- it
    # is the same marker -- and is flagged for the same reason.
    Screen(
        "Story Events", 0x00D53440, b"mc_da_2_text_off_l",
        in_adventure=True, marker_outlives_screen=True,
        state_address=0x00B054B0, state_value=1,
        event_list=EVENT_LIST,
        # F12: the question while it is up, else the synopsis box in the
        # second structure. The display pointer's line sits at y=486 on a
        # 448-line screen while the list is live, so it is not read then.
        prose_pointers=(0x008C6244, 0x008C6290),
    ),
    # The Game Level screen, reached after choosing a story event in Dragon
    # Adventure. Three boxes side by side reading 1, 2, and 3, arranged
    # horizontally, so it answers to Left and Right rather than Up and Down.
    # It opens on 2.
    #
    # The labels are the digits the screen actually shows. The game calls this
    # "Game Level" and the instruction line calls it the "Match level"; neither
    # says easy, normal or hard, so neither does the mod.
    #
    # One copy of the cursor: a plain count at 0x00B054A8, beside this
    # screen's own sprite names. **The mirror at 0x00432D71 is retired.** It
    # was recorded as the index times four, and on 2026-09-09, in a fresh
    # session, it read 0 while the screen showed 2; a spoken test then moved
    # the cursor Right and Left -- 1, 2, 1 at 0x00B054A8, each matching the
    # screen -- and the mirror stayed 0 throughout, as did its three
    # recorded copies. It was never a copy of this cursor, and reading it
    # had silenced the level on every first visit. No second copy is known.
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
        # No recorded subtitle: F12 read the instruction line from a fixed
        # address, and on 2026-09-09 the screen showed Goku's "Got it? The
        # next one's the last one!" there instead. The display pointer says
        # which, so F12 reads through it here like everywhere else.
        None,
        in_adventure=True,
        # The chosen event's number and name, drawn at the top of the
        # screen and said once after the screen's name -- "Game Level. 06
        # Training with King Kai". Read from the game's text, on two
        # captures from different sessions and different events, at
        # different indices of the array each time. This is the event name
        # F12 used to get wrong, now read from where the screen draws it.
        heading=EVENT_HEADING,
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
        "Select Scenario", 0x00D53440, b"mc_da_2_text_off_l", 0x00B0536C, 1,
        in_adventure=True,
        # **The story event list has the same marker**, because it draws
        # from the same allocation and the same sprite table, so this entry
        # also demands the Dragon Adventure menu byte at 0x00B054B0: 0 here,
        # on all thirteen captures of this list across four sessions; 1 on
        # the event list; 2 on Game Level. Measured 2026-09-09, and it is
        # what stops this screen being named over the event list, where the
        # cursor below would have said "Saiyan Saga" with total confidence.
        state_address=0x00B054B0, state_value=0,
        # **The cursor moved here on 2026-09-07, and the old one is refuted.**
        # A third scenario unlocked and the screen went silent. Read live at
        # all three rows, each paired with a screenshot:
        #
        #     highlighted        0x00D53625   0x00B0536C   0x00B05370
        #     Fateful Brothers        1            2            3
        #     Saiyan Saga             0            0            3
        #     Tree of Might           1            1            3
        #
        # `0x00D53625` reads 1 for two different rows, so it cannot be an
        # index -- it had been the cursor since this screen was mapped, and it
        # only ever looked right because a two-entry list makes every counter
        # of period two agree. `0x00B0536C`, until now the cross-check, is a
        # bijection, and it explains not just the highlighted row but the rows
        # drawn above and below it in all three screenshots: nine facts, not
        # three. It also agreed with the row on all seven two-entry captures.
        #
        # There is no cross-check left, and that is a real loss -- see the
        # Select Scenario section of docs/memory-map.md for the recipe to find
        # a genuine second copy. The old one was never a second copy of this;
        # it was a different quantity that a two-row list could not distinguish.
        # **Observed still resident after Dragon Adventure was left**, on the
        # main menu and on Options, for 168 consecutive frames of the
        # 2026-09-07 17:04 session. That is what took the main menu's name
        # away and handed its option subtitles to the story reader, and it
        # announced "Select Scenario" over the Options screen besides. The
        # address is kept because it is the only one that separates this
        # screen from Game Level, and it is now outranked rather than trusted.
        marker_outlives_screen=True,
        # **The game inserts, it does not append**, and it has done so twice:
        # Tree of Might landed at index 1, moving Fateful Brothers from 1 to 2,
        # and Lord Slug then landed at index 2, moving it to 3. So a row number
        # means something different after every unlock, and a table keyed by it
        # is not merely incomplete afterwards -- it is wrong.
        #
        # **`0x00B05308` is the game's own answer to "what is this row".** It
        # is an array of scenario numbers, one per row on a four-byte stride,
        # in the order the rows appear:
        #
        #     two entries    [0, 21]
        #     three entries  [0, 1, 21]
        #     four entries   [0, 1, 2, 21]
        #     five entries   [0, 1, 2, 3, 21]
        #
        # which is why Fateful Brothers keeps being pushed to the end and the
        # new scenarios keep arriving before it -- the list is the unlocked
        # scenarios in numerical order, and 21 sorts after 0, 1, 2 and 3. Names
        # keyed by that number do not shift when the list grows, so **an unlock
        # now costs one unnamed row rather than all of them.**
        #
        # Checked against all thirteen captures that have a screenshot beside
        # them, spanning four list lengths and several PCSX2 sessions: in every
        # one, the number at the highlighted row names the scenario in the
        # picture. The array is also identical at every row of the same list,
        # as a list's contents should be.
        #
        # **The design was then tested by the thing it was built for.** Final
        # Battle unlocked as number 3 and cost exactly one row: every other
        # name kept working. Under the arrangement before it, that unlock
        # would have cost all five names.
        #
        # Every scenario on the disc is now named ahead of time, so an unlock
        # should cost nothing at all -- see the table below.
        #
        # `0x00B05370` reads the length, and bounds the array read.
        id_array=0x00B05308, id_stride=4,
        count_address=0x00B05370,
        # **Every scenario on the disc, taken from the game's own name table.**
        # The notes long said these names were artwork found nowhere in memory.
        # They are in memory, as UTF-16LE text, in one table of all of them --
        # the same shape as the event-name table, which should have been the
        # hint. This list was walked out of that table rather than typed from
        # screenshots, so a scenario is named the first time the player ever
        # reaches it and nobody has to see the screen.
        #
        # Why the table is not simply read at runtime: it is loaded during
        # play, not with the screen. On a freshly booted emulator sitting on
        # this very list, a scan of all 31 MB found these names nowhere at all.
        # So they are read once, here, where they cannot go missing. See the
        # scenario-name table in docs/memory-map.md.
        #
        # **Anchored at five points**, each read off a screenshot of the row it
        # names: 0, 1, 2, 3 and 21. The anchor at 21 is what carries the rest --
        # a single insertion or omission anywhere between 3 and 21 would land
        # Fateful Brothers somewhere else, and it does not. Entries 22 to 24 sit
        # past the last anchor and rest on the table's order alone, which has
        # been exact for the twenty-two before them.
        #
        # **The table continues past 24 into battle stage names** -- Wasteland,
        # Namek, Kame House -- so it stops here. A scenario number the game
        # never uses costs nothing; a stage name spoken as a scenario would be
        # the confident error this project exists to avoid.
        labels_by_id={
            0: "Saiyan Saga",
            1: "Tree of Might",
            2: "Lord Slug",
            3: "Final Battle",
            4: "Frieza Saga",
            5: "Makyo Star",
            6: "Cooler's Revenge",
            7: "Return of Cooler",
            8: "The History of Trunks",
            9: "Android Saga",
            10: "Super Android 13",
            11: "Broly: The Legendary Super Saiyan",
            12: "Ultimate Future Warrior",
            13: "Bojack Unbound",
            14: "Majin Buu Saga",
            15: "Broly: The Second Coming",
            16: "Fusion Reborn",
            17: "Wrath of the Dragon",
            18: "Baby, The Avenger",
            19: "Ultimate Android",
            20: "Evil Dragon of Absolute Destruction",
            21: "Fateful Brothers",
            # "Beautfiul Treachery.." is the game's own spelling, kept as it
            # is: this table says what the screen says, not what it should say.
            22: "Beautfiul Treachery..",
            23: "Ultimate Science Battle",
            24: "Destined Rivals",
        },
        # A scenario number with no name is one the player has just unlocked.
        # Say which row it is and how many there are, and admit the name is
        # missing: honest, checkable, and it needs one line added here rather
        # than the whole table re-derived.
        unknown_row="Scenario {position}, name not known.",
        unknown_row_with_count="Scenario {position} of {count}, "
                               "name not known.",
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
        self._pending = None
        self._settled = None
        # Which draw slot spoke last, on a screen that reads several.
        self._last_slot = 0
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
        inside Adventure: the three Dragon Adventure menus and the Item Shop.
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
        if screen.state_value is not None and screen.state(pine) != screen.state_value:
            return False, False
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
        """Identify the screen, then the variant of it that is up, if any."""
        screen, trusted = self._detect_base(pine)
        if screen is None or not (screen.variants or screen.drawn_variants):
            return screen, trusted
        variant = screen.resolve(pine)
        if variant is None:
            self._note_once(
                f"menus: {screen.name} is in a state this build has not "
                f"mapped, so only its name is said -- "
                f"0x{screen.state(pine):02x} at 0x{screen.state_address:08X}")
            return screen, trusted
        return variant, trusted

    def _detect_base(self, pine) -> tuple[Screen | None, bool]:
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
        if len(weak) == 1 and not self._text_on_screen(pine):
            return weak[0], True
        return None, False

    @staticmethod
    def _text_on_screen(pine) -> bool:
        """Is the game drawing readable text through its display pointer?

        The title screen's raw signature is the only weak marker, and it has
        now been caught naming three screens that were not the title: the
        Game Level chooser, the Dueling character select, and -- flickering
        on and off, 2026-09-08 -- the Dragon Tournament entry screen, where
        the guide said "New Game" four times over a grid of fighters.  Every
        one of those screens draws text through the display pointer.  The
        title screen does not: on its capture the pointer aims at bytes that
        are not text.  Measured over all 44 captures on disk, the signature
        with no text on screen occurs on the title capture and nowhere else.

        So a weak marker is refused while text is on screen.  If the title
        screen ever draws a line, the cost is "Unknown screen" there, which is
        the safe direction; the cost of the old rule was a confident wrong
        name, which is the one this project does not pay.
        """
        from . import story
        try:
            return story.displayed(pine)[0] is not None
        except Exception:
            return False

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
                self.speaker.say(found.announcement(pine))
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

        if self.screen.speaks_names:
            self._speak_displayed_names(pine)
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
            label = self.screen.unknown_row_label(
                raw, self.screen.entry_count(pine))
            if label is None:
                return
        if label != self._spoken:
            self._spoken = label
            self.speaker.say(label)

    def _speak_displayed_names(self, pine) -> None:
        """Say the name the game is drawing for whichever slot just changed.

        Same discipline as a cursor: the names must read the same twice before
        they are trusted, and only a change is spoken.  The pointers are of the
        kind the story reader and F12 use, so a refusal there -- bytes that are
        not text, a stale pointer at a move list -- is a refusal here too.

        On arrival only the first slot is spoken, which on the character
        select is player 1's highlight.  After that, each slot speaks when its
        own text changes, with its prefix the first time the change comes from
        a slot other than the one that spoke last.
        """
        try:
            names = self.screen.displayed_names(pine)
        except Exception:
            return
        if all(name is None for name in names):
            self._pending = None
            return
        if names != self._pending:
            self._pending = names
            return
        if names == self._settled:
            return
        previous = self._settled
        self._settled = names
        if previous is None:
            for slot, name in enumerate(names[:self.screen.arrival_slots]):
                if name is not None and name != self._spoken:
                    self._spoken = name
                    self._last_slot = slot
                    self.speaker.say(name)
            return
        for slot, (name, prefix) in enumerate(
                zip(names, self.screen.name_prefixes)):
            if name is None or name == previous[slot]:
                continue
            line = name
            if prefix and slot != self._last_slot:
                line = f"{prefix}: {name}"
            self._last_slot = slot
            self._spoken = name
            self.speaker.say(line)

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
        from .story import displayed, read_displayed
        try:
            if self.screen is not None and self.screen.prose_pointers:
                # The screen says where its visible prose is drawn. No
                # fallback to the display pointer: on the story event list
                # that can aim at a line parked below the bottom of the
                # screen, and F12 says what is on screen or that it found
                # nothing.
                for address in self.screen.prose_pointers:
                    if EVENT_LIST.visible(pine, address):
                        return displayed(pine, address)[0]
                return None
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
