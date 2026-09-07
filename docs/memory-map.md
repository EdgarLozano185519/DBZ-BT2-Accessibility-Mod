# DBZ BT2 memory map (SLUS-21441, CRC FE961D28)

Addresses are PS2 EE physical addresses, read over PCSX2's PINE link. Every
entry records how it was verified. Nothing here is inferred from one screen or
one snapshot without saying so.

Tested against PCSX2 2.9.32. The guide's own docs cite 2.6.3.

## Why the mod reads indices, not text

BT2's menu labels are **pre-rendered artwork, not strings**. Verified from the
disc image:

- `SLUS_214.41` contains no English UI text in ASCII or UTF-16.
- The UI archives in `ZS2US_2.AFS` (`Menu.pak`, `Title.pak`, `Option.pak`,
  `DAdventure.pak`, `UBattle.pak`, `IShop.pak`, `DCenter.pak`, `DLibrary.pak`,
  `EZ.pak`, `Duel.pak`, `DTournament.pak`) contain no readable strings at all.
  Their byte entropy is 6.85 bits with ~11% zeros, which looks like raw texture
  data rather than compression. They were not decompressed, so this is strong
  inference, not proof.
- The executable holds sprite names indexed by number instead:
  `mc_item_name_%d`, `mc_chara_plate_%d_e`, `mc_title_text`.

So nothing in memory spells "Dragon Adventure". The game keeps the *index* of
the highlighted option; the words must come from our own table. Those tables in
`source/tools/menu_announcer.py` are the only place the text exists, and the
only thing that can ever be translated.

The Dragon Adventure scenario names go the same way: "Saiyan Saga" and "Fateful
Brothers" are in neither RAM nor the disc corpus, searched end to end, so they
are artwork too. This one hurts more than the fixed menus, because the scenario
list **grows with progress** while our table does not -- see Select Scenario.

**Story and tutorial text is the exception.** It is real UTF-16LE text in the
553 `TXT-US-*` files inside `ZS2US_1.AFS` -- 2,601 text boxes of cutscene
dialogue, narration and tutorials, extractable offline from the ISO and now
parsed by the disc's own format rather than scraped. See **Story text** below
for the format, for the scenario synopses that are resident in RAM at known
addresses, and for what is still missing before any of it can be spoken.

## Screen identification

Each menu reuses the same memory for its own purposes, so a cursor address is
meaningless unless the right screen is up. `0x00AA12A8` is the main menu cursor,
but on Options the same byte reads 163 and on Dragon Library 208. Reading it
blindly names options at random.

Screens identify themselves by loading their own sprite names into memory.
Detection reads a short string at a fixed address.

Most screens are told apart in the dynamic region around `0x00A00000`:

- **Main Menu** -- `mc_menu_lineanime` at `0x00AA15EC`
- **Options** -- `mc_icon_saveload` at `0x00AFCF85`
- **Dragon Library** -- `mc_musicprogram_0` at `0x00AB1FAF`
- **Title** -- no unique sprite name; identified by the 12-byte signature
  `01 80 00 00 00 00 00 C4 E1 06 53 53` at `0x00533D60`. **This signature is
  not exclusive**: it also matches on the Game Level screen. It is therefore
  treated as weak evidence -- see below.

**The two Dragon Adventure screens cannot be**, and are found in a second
sprite-name table around `0x00D52000` instead, entries at a `0x40` stride:

- **Select Scenario** -- `mc_da_2_text_off_l` at `0x00D53440`
- **Game Level** -- `mc_da_5_lv_csr` at `0x00D547C0`

The dynamic region is **identical between those two screens, to the byte**, so
nothing in it can separate them; the second table is rewritten per screen and
does. This was found the hard way -- see Select Scenario. Do not assume the
dynamic region is where a marker must live.

Match markers as a **prefix**. The main menu's name is `mc_menu_lineanime`; an
exact comparison against a 16-byte window clipped the trailing "e" and failed.

A readable marker beats a state number because it can be checked rather than
trusted.

**Named markers outrank raw signatures, and ambiguity means silence.** Markers
were assumed to be mutually exclusive, and detection returned the first that
matched. That assumption was wrong: the title screen's byte signature also
matches on the Game Level chooser, and because Title is checked earlier it
shadowed it -- announcing "New Game" over a difficulty menu. Detection now
checks every screen. A single matching sprite name wins; two matching names
means the mod does not know where it is and says so; a raw signature is
consulted only when no name matches at all.

Verified against every capture on disk: Game Level, Options, Main Menu and
Title each identify correctly. Note the static string table at `0x00428280` holds these same names on
*every* screen -- only the copies in the dynamic region are screen-specific.

**Confidence.** The main menu marker held the same address across 19 captures
and survived a full out-and-back transition, and again across an emulator
restart. The Options marker has now been seen in two separate PCSX2 runs, on
four visits. Dragon Library still rests on a **single visit**; its address could
shift and has not been re-verified.

## Title screen: New Game / Load Game

- `0x00533A73` (byte) -- **cursor index x 2**. `0` = New Game, `2` = Load Game.
  Mirrored at `0x00533A83`. `0x00533A93` / `0x00533AA3` carry the same signal
  offset by two.

Why the stride is two is **unknown**. The main menu does not do it, so stride is
per-screen and must not be generalised.

**Verified** across 14 paired screen-and-RAM captures, plus 16 of 17 live frames
with a stability guard. The single outlier is consistent with `PrintWindow`
returning a stale frame.

## Main Menu: ten options

- `0x00AA12A8` (byte) -- **cursor index, 0 to 9**, plain, no stride. Mirrored at
  `0x00CF9C34`.

- `0` Dragon Adventure (the story mode)
- `1` Ultimate Battle Z
- `2` Dragon Tournament
- `3` Dueling
- `4` Ultimate Training
- `5` Evolution Z
- `6` Item Shop
- `7` Data Center
- `8` Options
- `9` Dragon Library

Seven of these correspond to `.pak` archives on the disc, which corroborates the
labels read off screen.

**Verified** by a live walk of the whole menu four times over with no wrong
label and no gaps.

## Options: five entries, and two copies of the cursor

A vertical list, not a carousel, but it **wraps** at both ends, so the press
scan's modular analysis applies unchanged.

- `0x00AF7294` (byte) -- **cursor index, 0 to 4**, plain, no stride. Sits in the
  block Options allocates for itself, beside its own marker.
- `0x00532173` (byte) -- the **same index doubled**, in static memory. Mirrored
  at `0x00532183`; `0x00532193` and `0x005321A3` carry the signal offset by two.
  A second copy at `0x004320F3` behaves identically.

- `0` Save and Load, `1` Controller, `2` Screen, `3` Sound, `4` Exit

Labels were read from a screenshot and are independently corroborated by the
sprite names `mc_icon_saveload`, `mc_icon_controller`, `mc_icon_screen` and
`mc_icon_sound`.

**Verified.** A press scan of 18 varied samples matched **five options and
nothing else** -- every other menu size from 3 to 16 produced zero candidates,
which is strong independent confirmation of the option count. Narrowing the
39,101 raw matches to values that can actually be an index left 5 addresses in
these two families. All five then tracked the cursor correctly across a
departure to the main menu and a re-entry, a transition they were not derived
from, and all five kept their addresses and their agreement across a full
emulator restart.

The cursor **resets to the top on re-entry**, and off Options both families go
stale (`0x00532173` reads 0, `0x00432103` reads 48) regardless of what is on
screen. Neither means anything unless the marker says Options is up.

**Both copies are read, and an option is spoken only if they agree.** A single
address cannot tell a correct read from a drifted one; two can. A disagreement
is treated as "read again", not as "no such option" -- otherwise one unlucky
frame would mute an option until the player navigated away and back.

## Game Level: choosing a difficulty in Dragon Adventure

Reached after picking a story event. Three boxes side by side reading 1, 2 and
3, so it answers to **Left and Right**, not Up and Down. It opens on 2.

- **Marker** -- `mc_da_5_lv_csr` at `0x00D547C0`, in the per-screen sprite-name
  table. **The marker used to be the same name at `0x00B1007B`, and that was
  wrong**: it matches on Select Scenario too, because the two screens share
  their whole dynamic allocation. See Select Scenario below. The copy at
  `0x00D547C0` is absent on all seven Select Scenario captures and on every
  other screen.
- `0x00B054A8` (byte) -- **cursor index, 0 to 2**, plain, beside the marker.
- `0x00432D71` (byte) -- the **same index times four**. Mirrored at
  `0x00432D91`, and again at `0x00532DF1` / `0x00532E11`; the `+0x10` neighbours
  of each carry the signal offset by four. The same static-mirror idiom as
  Options, at a different stride.

- `0` Level 1, `1` Level 2, `2` Level 3

The labels are the digits on screen. The game calls this "Game Level" and its
instruction line calls it the "Match level"; **nothing says easy, normal or
hard**, so neither does the mod.

Two lines of real text sit alongside, identical in all six captures:

- `0x00D1A782` -- **not the current event name.** See below.
- `0x00D179C2` -- "Set the Match level to your strength. You can always adjust
  it later!"

Both are read on **F12**, not spoken automatically.

**`0x00D1A782` is entry 0 of a table, not a display slot.** It was recorded as
"the event name" from captures taken on event 00, where the two are
indistinguishable. They are not the same thing: the address is the first entry
of a table of event names holding 230 entries in 240 granules of `0x40` each,
beginning

    0x00D1A782  Mysterious Alien Warrior
    0x00D1A7C2  Kakarot
    0x00D1A802  Common Enemy
    0x00D1A842  Gohan and Piccolo

and it reads "Mysterious Alien Warrior" **on the Select Scenario screen too**,
where no event name is displayed at all. So F12 does not report the current
event; it reports the first one, always. This is the confident error the
project treats as worse than silence, and it is live in the shipped build.

Fixing it needs the index of the current event, which is not yet known -- the
story event list, still unmapped, is the obvious place to look for it.

**The table is not regular, and `0x00D1A782 + 0x40 * n` is the wrong fix.**
Walking it (`python story_probe.py names`) gives 230 entries in 240 granules,
because a name longer than 31 characters fills its granule and continues in the
next one:

    granule  38  Frieza's Ultimate Transformation!     (spans 38 and 39)
    granule  76  New Piccolo: Desperate Resistance
    granule  99  Three Super Saiyans Vs. Legendary Super Saiyan
    granule 123  Destined Battle: Goku Vs. Vegeta
    granule 166  Immortal Monster?! Evil Giant Ape Baby
    granule 171  Ultimate Android! The Two 17s Fuse

From granule 38 onwards the granule number and the event number drift apart,
and at least one granule (200) is empty besides. Arithmetic indexing would read
a continuation fragment -- "n!", "pe Baby", "use" -- and speak it confidently,
which is the same class of error as the one being fixed. The table has to be
**walked** from the start: a granule with no null terminator inside it is
continued by the granule after it. `story_probe.names` does exactly that and is
the reference implementation.

The event names end at granule 216; granules 217 onwards hold a separate list
of the numeric strings "00" to "22" and are not names at all.

The instruction line at `0x00D179C2` is unaffected: it is the same sentence for
every event, so a static table entry is the right answer there.

**Verified.** Six captures at screen positions confirmed from the screenshots
rather than assumed -- 2, 1, 2, 3, 2, 1 -- left exactly nine surviving
addresses, all nine of them index ramps, in the two families above. Read back
live afterwards, correctly, on the same screen. **Not yet checked across a
departure and return**, which is the standard this project holds cursors to.

**This screen sits inside Dragon Adventure, and the HUD detector calls it
gameplay.** `has_dragon_adventure_hud` returns true on every capture of it, so
the guide treated it as play, suspended menu reading and said nothing at all --
the first symptom reported from a live run. Menu reading is no longer gated on
the pixel heuristic alone: a screen flagged as living inside Adventure is looked
for in memory each frame, and finding its marker overrules the heuristic. A
marker that can be checked beats a heuristic that can only be trusted.

The cost is one short read per frame during play, for each screen flagged so
far -- two now, this one and Select Scenario. The pixel heuristic is left
alone: it is load-bearing for navigation, and this screen is a menu whatever it
looks like.

## Select Scenario: the Dragon Adventure scenario list

The list of scenarios, reached from Dragon Adventure before the story events
and the Game Level chooser. A vertical list that wraps; the highlighted row
stays centred and the names scroll through it. On this save it holds two
entries, so the row above and the row below show the same one.

- **Marker** -- `mc_da_2_text_off_l` at `0x00D53440`.
- `0x00D53625` (byte) -- **cursor index**, plain, beside the marker.
- `0x00B0536C` (byte) -- the **same index**, in the other allocation entirely.
  `0x00D53634` carries it doubled, unused.

- `0` Saiyan Saga, `1` Fateful Brothers

**This screen and Game Level cannot be told apart by any marker in the dynamic
region.** `0x00A00000`-`0x00C00000` is identical between captures of the two
screens **to the byte** -- 0.00% differing, against 97-99% for every other pair
of screens. That is why `mc_da_5_lv_csr` at `0x00B1007B` matched here and the
mod believed it was on the difficulty chooser. Nothing about that address was
wrong; the region simply does not change between these two screens, so no
marker in it can ever separate them.

What does separate them is the **per-screen sprite-name table** around
`0x00D52000`, entries at a `0x40` stride, which is rewritten per screen:
`mc_da_2_*` names on this screen, `mc_da3_*`, `mc_da4_*` and `mc_da_5_*` on
Game Level. Both screens' markers now come from there, and both were checked
against all thirteen captures on disk: each matches its own screen and nothing
else.

**Verified.** Six captures cued Down, Down, Up, Down, Down, Down, each paired
with a screenshot, and the positions were read back off the pictures rather
than assumed -- 0, 1, 0, 1, 0, 1, the Up press toggling like a Down because the
list has only two entries. `fit` left 47 surviving addresses of which 4 are
index ramps, in the two families above. A seventh capture taken in a separate
PINE session before the scan began agrees with all four, and is genuinely held
out. Detection and cursor were then replayed offline against all thirteen
captures with no mismatch, and confirmed live on the screen itself.

Because the list has two entries, position is only parity, and any counter with
period two fits the press schedule as well as the cursor does. The four
survivors are believable because they also **differ from the Game Level
capture** and are small enough to be an index -- not because the press schedule
was selective. A third scenario would make this much stronger, and re-checking
it then is worth the minute it costs.

**The labels hold for this save's unlock state only.** The names are artwork,
like every other UI label here: "Fateful Brothers" and "Saiyan Saga" appear
nowhere in RAM and nowhere in the disc corpus, searched end to end. So the
words have to come from a table we wrote, indexed by cursor position, and that
table is only true while the list is what it was when it was written.

This is the only screen here whose length is not ours to know, and it is the
one case where an unnamed row means the player has been playing rather than
that something is broken. So it does not fall silent on one: it says
**"Scenario 3, name not known."** Silence would be indistinguishable from the
mod failing, which is the fault this project exists to avoid, and a position is
honest in a way a guessed name would not be.

That announcement is also the **tripwire for the dangerous case**. Growth at the
end is harmless. **Insertion is not**: a newly unlocked scenario landing above
"Fateful Brothers" would shift it, and the mod would say the wrong name with
full confidence and no warning. Nothing in memory distinguishes a position from
a scenario identity while the list has only two entries in order, so this cannot
be settled now. Hearing "name not known" means the list has grown and **every
name on this screen must be re-checked**, not merely extended.

Bounded at `MAX_UNNAMED_ROW`: a cursor reading past that is far likelier to be
a bad read than a menu that long, and inventing a row number out of garbage
would be its own confident error. Tested at rows 3 and 4, at implausible
values, and with the mirrors disagreeing.

## Subtitles: the game's own words, in memory

On-screen prose is held in EE RAM as verbatim UTF-16LE. This is the opposite of
the menu labels: no table has to be authored, because the game's own text can be
read directly. Announced on **F12** (unbound in PCSX2; it binds F1-F6, F8, F9).

The main menu's ten spoken lines sit in cursor order:

- `0x00CA9A42` Dragon Adventure, `0x00CA9B02` Ultimate Battle Z,
  `0x00CA9B82` Dragon Tournament, `0x00CA9C02` Dueling,
  `0x00CA9CC2` Ultimate Training, `0x00CA9D42` Evolution Z,
  `0x00CA9E02` Item Shop, `0x00CA9EC2` Data Center, `0x00CA9F42` Options,
  `0x00CA9FC2` Dragon Library

Verified by matching three of them against captures whose cursor value was
known. The same block also holds the boot health warnings and the title text.

These lines are **subtitles for voiced character dialogue** -- the player
identified this from hearing them. That matters: it means the game has a working
subtitle system, and cutscene subtitles are likely to use the same machinery.
`ZS2US_2.AFS` holds over 4,000 `VIC-US-*` files, almost certainly those voice
clips.

**These addresses come from a single PCSX2 run** and the block does move between
runs. Every read is checked for plausible text before being spoken, so a moved
block produces "no subtitle available" rather than gibberish.

**The block is now found again by its shape.** When a recorded address stops
reading as text, the mod searches `0x00C00000`-`0x00D00000` in half-megabyte
steps for ten readable UTF-16LE lines at exactly the spacing above, and
remembers the offset for the rest of the session. No line of game text is
hardcoded, so nothing has to be transcribed and the search is not tied to
English. Ten independent hits at fixed offsets is the selectivity: synthetic
random RAM produces no match, and an empty region produces none either.

The search reads about a megabyte and takes well under a second, but it is
announced ("Looking for the subtitles.") because an unexplained pause is
indistinguishable from a crash for a player who cannot see the screen. It runs
only after a failed read, never on the happy path, and no more than once every
twenty seconds.

Note these menu lines are **not** among the 2,601 `TXT-US-*` story strings --
zero matches. The game has at least two separate text sets, so reading RAM
covers text the offline extraction misses entirely.

## Story text: the disc format, and what is resident

**The disc format is fully decoded.** `extract_text.py` used to pull strings out
of `TXT-US-*` with a regex over printable ASCII. That produced 2,458 lines and
looked right, but silently split every line containing a typographic apostrophe
(U+2019, 17 of them) or an ellipsis character, leaving fragments -- "Okay,
Vegeta, now it" and "s your turn." -- that match nothing in RAM. A fragment is
worse than a miss here: it makes the corpus filter quietly weaker exactly where
the text is most distinctive.

Each file is self-describing, so it is now parsed rather than scraped:

    u32   slot count            (5, 6, 10 or 30 on this disc)
    u32   [count + 1] offsets, the last marking the end
    ...   padding to an 8-byte boundary
    each slot: a UTF-16LE BOM (ff fe), the text, a null terminator

An unused slot is two equal offsets, so a slot's index is its position in the
file. All **553 files parse, giving 2,601 text boxes** -- exactly the count
arrived at independently before, which is the check that the format is right
rather than merely plausible. Line breaks inside a box are real: they are where
the game wraps its text box, and they are kept in `story_scenes.json` and
collapsed only for speech.

**A file is a scene, and the slots are in the order the game shows them.** That
is what makes the search tractable: a box found in RAM identifies not only that
the bytes are game text, but *which* scene and *how far through it* the game
has got.

    TXT-US-A-00-0@0x1018e000
      [0] Goku and his friends were enjoying a happy reunion, when...
      [1] ...That's definitely Kakarot. He looks exactly like his father...
      [2] Who the heck are you?!
      ...

The series prefix says what kind of text it is: **A** is Dragon Adventure
cutscene dialogue (414 files, 25 events), **O** is one scenario introduction
each (26 files), **E** and **F** are tutorials and challenges.

### The scenario-synopsis pool, resident at 0x00D1E3C0

Scanning the kept captures with `story_probe.py scan` gives a clean split:

- Main Menu, Options, Title, Dragon Library -- **no story text resident.**
- Game Level and Select Scenario -- **123 boxes, the entire O series**, all 26
  scenario introductions laid out in file order from `0x00D1E3C0` to
  `0x00D24D40`, packed on `0x40` granules with their BOMs intact.

So the pool sits immediately above the event-name table, and the two together
are a Dragon Adventure text pool that loads on entering the mode.

**There is no pointer table into it, and no display copy.** Searching all 31 MB
for pointers to the pool's entries -- raw and kseg0 -- finds none, and the six
Select Scenario captures taken at different cursor rows hold the pool
**byte for byte identical**. Nothing stages the highlighted scenario's synopsis
anywhere; the renderer reads the pool at a computed offset and draws it. That
matches what the menu captures already showed, and it means reading these
screens needs the same missing piece as the event name: **an index.**

### 0x008C6244 -- a pointer to the text on screen, everywhere

**Found 2026-09-07** from eight captures taken through one Dragon Adventure
cutscene, and it is bigger than the cutscene problem it was hunting.

The capture session (`story_probe.py capture`) recorded RAM and a screenshot
together each time the text box changed, while the player advanced at their own
pace. The screenshots gave the ground truth -- boxes 0, 1, 2, 2, 2, 3, 4, 4 of
`TXT-US-A-00-0`, the Saibaman scene -- without anyone having to read the screen
during the run.

**The scene file is copied into RAM whole, header and all**, at `0x0109FB40`:
slot count, offset table, then the BOM-prefixed boxes, byte for byte as on the
disc. Text therefore starts at `+0x30`, which is where the boxes were found.
The next scene loaded into **the same base**, so the buffer is reused rather
than allocated per scene.

`0x008C6244` holds a **pointer to the box currently being drawn**. It was the
only address in all 31 MB that tracked the slot exactly, and the values it held
are precisely the header's offset-table entries for those slots. It sits at the
head of what is clearly a text-draw structure:

    +0   pointer to the text
    +4   two packed 16-bit numbers, position or extent
    +8   the second of them again
    +12  1.0f, +16 1.0f -- scale

**It is not cutscene-specific, and that is the point.** Checked against nine
captures it was *not* derived from, it points at whatever prose is on screen:

    auto0       Main Menu       "You can set options during the game..."
    press0      Options         "During the game you can change the camera..."
    diff0       Game Level      "Set the Match level to your strength..."
    library     Dragon Library  "You can read everyone's profile..."
    events0     Select Scenario "What's wrong? Have you lost your nerve?"
    posn0/3     Select Scenario "Man, I'm hungry..."

So one address supersedes the ten hardcoded main-menu subtitle addresses and
the shape-based search that relocates them, gives the Game Level instruction
line without a table, and reaches Dragon Library and Select Scenario text that
is not mapped at all.

**Verified live, on scenes it was not derived from.** Read back during two
later cutscenes, each loaded at a **different base** from the one the address
came from (`0x0109F340`, not `0x0109FB40`), and matched against a screenshot
taken at the same moment:

    pointer said  "Krillin unleashes the full force of his anger upon the
                   remaining Saibamen."      screen: the same, line breaks and all
    pointer said  "Tien! My telekinesis won't work!"   screen: the same

`story_probe.py follow` then read six consecutive lines aloud as the player
advanced, with no repeat, no fragment and no line that was not on screen. That
is the transition test the two byte candidates failed, passed three times.

**It reports system text too.** One of the six lines was "MEMORY CARD slot 1" --
not story text, but genuinely on screen, so the pointer was right and the
mental model of "story subtitles" is too narrow. Whether a save notice should
be spoken is a judgement for the player, not a bug to filter away silently.

**It does not move between runs.** The nine screens above come from three
separate PCSX2 sessions across two days, and `0x008C6244` read correctly in all
of them. That is the difference between this and the ten recorded subtitle
addresses, which came from one run and move: this needs no relocation search.

**What the reader refuses, and why each check earns its place.** In
`bt2/story.py`, covered by 28 offline checks in `test_story.py` -- nine of them
against real captures whose expected text was read off the screenshots taken
beside them:

- The pointer must land inside EE RAM and its target must start with a BOM.
- The text must terminate within 400 bytes; no box on this disc is longer.
- **Control codes are refused, printable ASCII is not the test.** Eighteen real
  story boxes contain a typographic apostrophe or an ellipsis, so an
  ASCII-only check would have gone silent on "Okay, Vegeta, now it's your
  turn." -- the same mistake the disc extractor made, in the place where it
  would have been hardest to notice.
- **Text with a `#`, `$` or `%` at the start of a line is refused.** Move lists
  and tutorial pages mark up their layout that way; not one of the 2,601 story
  boxes does. This is what separates a story line from the move-list text the
  stale pointer was caught aiming at, and it is structural rather than
  linguistic, so it is not tied to English. A `#` mid-line is an android's
  name and is kept.

**The pointer is stale whenever nothing is being displayed.** After a cutscene
ended and a battle began it went on aiming at the last thing drawn, and was
seen pointing at move-list text ("Charge with the triangle button") with no
text box on screen; on the title screen (`pos0`) it aims at bytes that are not
text at all. Reading on change alone therefore leaks **one stray line** on the
way out of a cutscene. Two guards, both already proven elsewhere in this
project: refuse anything that does not decode as clean text, and read only when
the screen state says prose is up. The first is in `read_displayed` now; the
second is not written yet and is what still stands between this and shipping.

Two byte-sized candidates found first, `0x00FFB1C4` and `0x003B29BC`, matched
the box sequence across all eight captures and were the only two bytes in 31 MB
to do so. **Both are refuted.** On the next scene they disagreed with each other
and with the screen, and `0x003B29BC` moved 7 to 0 between two reads seconds
apart. An eight-sample match on slowly-incrementing counters is not the evidence
it looks like -- which is the whole reason the rule is to verify on a transition
the candidate was not derived from.

### How the capture session actually went, and two wrong estimates

No **A**-series text is resident outside a cutscene -- zero hits in every kept
capture -- so cutscene dialogue is streamed per scene and the session had to
happen inside one. Two things assumed beforehand turned out to be wrong, and
both were wrong in the direction of making the work look harder than it was.

**A full 31 MB read takes 0.6 seconds, not ten.** The ten-second estimate came
from reading the subtitle-search note ("about a megabyte, well under a second")
and scaling it up. Measuring instead of scaling would have taken one command.

**A text box waits for a button press.** The scene region was byte-identical
over fifteen seconds, so nothing runs away and there is no race to win.

Together those killed the entire pause-and-coordinate protocol the plan called
for. `story_probe.py capture` replaces it: it watches the screen, and every
time the text box changes it records RAM and the picture together. The player
just plays. A capture is kept only if the screen still shows the same box after
the read finished, so a press landing mid-read cannot pair one box's picture
with another box's memory -- that happened twice in eight captures and both
were correctly discarded and retried.

    python story_probe.py capture cut --boxes=8   # the player advances; that is all
    python story_probe.py scan cut0               # which scene loaded, and where
    python story_probe.py compare cut0 cut1 ...   # display slot, or resident block?

`compare` sorts the addresses holding story text into the two possible answers:
one holding a *different* known line in each capture is a display slot and is
the whole feature; one holding the *same* line every time is a resident block
and would report what is loaded rather than what is shown. Keeping those apart
is the point -- `0x00D1A782` was recorded as a display slot when it is a table
base, and still announces the first event's name on every event.

In the event `compare` found **no** display slot: all eight known boxes were
resident and static. The answer was a pointer rather than a copy, which is why
the search that found it looked for *an address holding a pointer to the
current box* rather than for text that changed.

Note `menu_probe.py snap` stops at `0x01000000` by default. The cutscene scene
file loaded at `0x0109FB40`, above that line, so a snap without `--full` would
have missed the entire thing.

## Screens seen but not mapped

- **Dragon Library** -- detected only.
- **Ultimate Battle Z** -- not detected at all. The announcer correctly says
  "Unknown screen" there, which is the intended behaviour: naming a screen it
  cannot read would be worse than admitting it.
- **The story event list** -- the screen between Select Scenario and Game
  Level, where the individual events are chosen. Not captured, not detected.
  It is the likeliest home of the current-event index that would make the F12
  event name honest, so it is now the highest-value screen left.

## The player's facing, on the world map

Guidance tones are stereo: left and right. On the world map they were panned by
the *world* offset -- screen right on the minimap is east -- so the tone said
"the objective is east" whether the player was flying east, west or backwards.
A sighted player reads their heading off the screen and the cue works. A blind
player cannot, and the cue is unusable. Indoors this was never a problem,
because local surfaces already carry the player's own axes.

The game keeps the player's orientation as a conventional 4x4 transform whose
translation row **is** the position the guide already tracks, so the matrix
begins `0x30` bytes earlier. `memory.parse_transform` already validated exactly
this shape; nothing new had to be understood, only located.

- `player_address - 0x30` -- the player's 4x4. `values[0], values[2]` are the
  right axis, `values[8], values[10]` the forward axis, `values[12:15]` the
  position.

**Found by structure, not by correlation.** A search of `0x00100000`-`0x01800000`
for orthonormal matrices whose translation equalled the live player position
returned 16 hits and no false ones. Requiring the translation to match is what
makes it the player's transform rather than one of the many other rotation
matrices in memory, and `player_frame` re-checks that on every read.

**Verified live.** Sampled at 4 Hz while the player flew and turned on spoken
cues, the forward axis swung through a left turn and back through a right. The
16 copies fall into two groups differing by a fraction of a degree -- one lags
the other by a frame, matching the simulation/render split already known here.
Whether this is the character's facing or the chase camera's cannot be told
apart while flying, and does not matter: the two are locked together, and it is
the frame the controls operate in either way.

## A chosen destination must be held, not looked up again

The list of destinations is rebuilt from the minimap every frame. The player's
choice used to be stored as an index into that list and resolved again on each
use, and `selected_location` quietly fell back to the first entry when the
index was not found:

    for entry in available:
        if entry.location.index == self.state.selected_index:
            return entry.location
    self.state.selected_index = available[0].location.index   # silent

So a marker that dropped out of the inventory for a single frame moved the
selection to the first destination without a word, and a teleport went
somewhere the player never picked. Reproduced exactly: choose map point 4,
remove its marker for one frame, and the old path returns map point 1.

A decision is now held as the destination itself -- and the words it was
announced with, so a teleport cannot rename it either. Coordinates do not go
stale; only a change of map invalidates the choice, and `reset_surface` clears
it there.

The general lesson: **anything the player decided should be stored, not
re-derived from state that the guide rebuilds.** Re-deriving turns a transient
gap in perception into a silent change of intent.

## A table's player slot can go dead while the table is still current

Liveness is decided by whether the table's own player slot, at table+0x500,
follows the live player. Returning to Earth after a story event, that slot sat
**frozen** at (-24.8, 0.0, 10.2) while the player was at (-27.3, -138, -335) --
a planar gap of 345 against a tolerance of 20. The table, its eight
destinations and the minimap were all plainly the live ones; only the slot had
stopped being written.

The guide therefore refused the correct table and reported no destinations at
all, on a map that had been working minutes earlier.

**The fallback:** when nothing confirms itself live and exactly *one*
well-formed table exists in the whole of RAM, use it, and say so once. The
structural test is strict enough to have produced no false positives across
~950 MiB, and "the only table there is" is a much weaker assumption than "the
first table found", which is the failure the liveness check was written to
prevent. Two tables and no liveness still refuses: that is genuinely not
knowing which map is current.

`Surface.liveness_confirmed` carries this, and the guide announces it rather
than quietly presenting an unverified table as a verified one.

## Choosing between resident tables, and noticing markers change

Two consequences of the frozen-slot finding, both now handled.

**More than one table can be resident.** The single-table fallback rescued the
observed case but would have refused again the moment a previous map's table
was still in memory alongside the current one. When several tables exist and
none confirms itself live, geometry decides: the player should be standing
inside the destinations that describe them, so a table whose padded bounding
box excludes the player is discarded, and the nearest-destination distance
breaks the remainder. If two tables both claim the player and neither is
clearly closer, discovery still **refuses** -- guessing which map you are on is
the exact failure the liveness check exists to prevent. One table on its own is
still accepted unconditionally; there is nothing to confuse it with.

**Markers change without the map changing.** `MinimapInventory` made confirmed
destinations permanent for the visit, deliberately, so that the player's arrow
covering a dot could not delete it. But finishing a story event rearranges the
markers while the map stays the same, and the guide went on offering the set it
first saw. A confirmed destination is now dropped after `LOST_FRAMES`
consecutive frames unseen -- about seven seconds, far longer than an arrow
lingers -- and the census is re-announced when its description changes, as
"Destinations changed: ...". Comparing the description rather than the blobs
means a dot flickering under the arrow cannot cause chatter.

Measured: absent for 8 frames, kept; absent for 31, dropped; a new marker
admitted normally.

**Confirmed in play on 2026-09-06** for the map-change case: loading a new map
updates the destinations correctly and the player progressed through the story
on it. The in-place case -- a story event rearranging markers while the map
stays the same, which announces "Destinations changed" -- has still not been
observed, and should not be reported as working until it is.

## An input held is better than an input dropped

The destination keys were being read correctly -- a spy on the poll showed
`'next'` arriving for every press -- and still nothing happened. The pass that
catches a press is often one that cannot act on it: no table yet, scene not
ready. The press was read into a local, that pass gave up, and the press went
with it.

Presses are now held on the state until a pass can serve them, and only after
`PENDING_ACTION_PATIENCE` does the guide give up and say why. Reading the input
early is not enough; it has to survive the passes that cannot use it.

## Hotkeys must be read before the loop gives up

Twice now the same fault has appeared with a different key. The loop abandons a
pass whenever the story objective has not resolved:

    if state.objective is None: continue
    if not state.objective.has_direction: continue

Anything read *after* those lines is silently discarded in exactly the
situations the player most needs it. G was read there, and worked only
sometimes. The destination keys were read there too, so on a fresh map --
where no objective has resolved yet -- N and B did nothing at all, with no
error and no sound.

Choosing where to go, and asking how far away it is, do not depend on the
objective being ready. Both are now read at the top of the pass, and every
branch that gives up early answers rather than staying silent.

**When adding a key, ask what it needs.** If it does not need the objective, it
must not be read behind the objective's guards.

## The story objective is a screen object, not a table entry

On the world map the guide follows the red minimap marker directly, and
`survey_map` deliberately leaves `state.available` empty:

    # Kept empty deliberately: available destinations are screen objects,
    # not table locations.

So N and B cycle the coordinate table, which is a *different* set from the
markers -- 8 table points against 6 markers in one observed frame. The red
story marker has no table entry, which is why cycling never used to announce a
story event, and why "press N until you hear Story" was wrong advice.

**That is no longer true, and the change is the point of this section.** Once
the map is calibrated the marker *can* be converted, so `cycle_destination`
appends it as the last entry in the cycle -- "Fly northeast for 1171 units
toward the story marker. 9 of 9." It is converted live through the projection
on every press rather than stored, so it stays right as the player and the
marker move. Before calibration it is simply absent from the cycle, which is
honest: offering it would promise a teleport that cannot happen.

**Choosing with N or B used to take the story marker away for good.** The first
press set `destination_chosen`, which is cleared only by `reset_surface` -- so
after one press T followed the chosen table point and nothing but leaving the
map could give the story marker back. This was found by reading the code and
then met head-on in play: the player calibrated, teleported to the story marker
twice, pressed N to browse, and T stopped reaching it. The story slot is the
fix; `story_selected` marks it so T and G use the live marker rather than the
frozen pick.

Converting the red marker to a world coordinate needs the minimap-to-world
scale. The original way to learn it was to watch the player fly, and **a player
who cannot see the screen cannot fly**, so that route was closed to the very
user this mod exists for. That is the problem the next section solves.

**A one-frame fit from markers to table points does not work.** Tried: solve a
per-axis scale and offset by matching the yellow markers against the table.
The best fit matched 4 of 5 markers but produced a negative x scale, against
the documented "increasing X moves right", and failed its own held-out check --
the player's own position, never used in the fit, predicted a screen position
98 px from any arrow. The code's existing warning that pairing the census back
to the table caused wrong-route fallbacks is well founded.

**What works today:** the story event has been reached by teleporting to table
points one at a time and trying the action button at each. Crude, but it needs
no flying, and the player reports it as acceptable.

**What is built, and confirmed in play on 2026-09-07:** teleport *is* movement. The
calibrator learns from pairs of world delta and screen delta and does not care
how the player moved, so `bt2/mapcal.py` on the **C** key commands six short
hops and solves the Jacobian from those. The Jacobian is saved per map profile,
so it is a one-time cost per map.

Three things about it are worth knowing before touching it.

**The hops must be small.** Not for the player's sake -- for the matching. The
arrow is identified by following white blobs across the run, and a hop that
moves it further than the match radius makes it a *new* blob with no history,
which the solve then refuses as "the arrow was not visible for the whole run".
So the first hop is a deliberately cautious probe, and the rest are sized from
what it measured. At the documented 0.00004 scale a 461-unit probe moves the
arrow about 25 px against a 73 px radius.

**A hop must not land on a destination.** The game tests a sphere; a calibration
hop that lands inside one starts an event the player did not choose. Every
waypoint is checked against every table point before the run begins, and a spot
with no clear quadrant is refused with a reason rather than risked.

**The pause is what the loop nearly broke on.** A run spends half its time
paused, and the loop gives up on the minimap after three frames without one --
which a paused frame can be, because PCSX2 dims it below the white detector's
threshold. `paused_holding_route` in `guide.py` already covered a paused player
holding a route; it had to be widened to cover a calibration run, which is
usually on a map with no route yet. Without that the run can never observe the
pause it just asked for.

The **arrow anchor** matters as much as the scale and is easy to miss.
`locate_arrow` follows the arrow by predicting where it went, which needs a
last known arrow position to predict from. On a map nobody has flown there is
none, so a Jacobian alone sits unusable. `mapcal` returns the winning blob's
final screen position with the scale, and `adopt_calibration` publishes both.

**And the teleport handler used to throw that anchor away.** It cleared
`state.last_arrow` after every world teleport, so the guide asked the player to
"move briefly so the player arrow can be identified" -- of a player who cannot
move, immediately after the one action that moves them. In the live run that
line repeated eleven times in three seconds. With a confident calibration the
anchor is now kept: the prediction accounts for the whole jump, and the search
radius is around the *predicted* position rather than the old one.

### What the first live run measured

2026-09-07, the recorded "Blue landmass" profile, at a 1066x705 capture:

    jacobian  [ 4.242e-05, -3e-08, 1.2e-07, -5.456e-05 ]
    6 movements spanning 90 degrees, cross-checked to 0.04% and again to 0.06%

Worth keeping because it is an independent confirmation of something this file
already asserted from a different method. `anchor.py` reasons that the minimap
is a fixed, unrotating, top-down view, so the projection is axis-aligned --
`px = a*x + c`, `py = b*z + d`, with no cross terms. The measured off-diagonals
are -3e-08 and 1.2e-07, which is zero to the precision available. The two
diagonal terms also land either side of the 0.00004 this file documents.

**The first attempt refused, and the refusal was right about the rule and wrong
about the case.** Every hop size was rejected because the square's home corner
sat inside a destination -- the player was dead centre of point 7, where a
teleport had just put them. But teleporting onto a destination and pressing the
action button is *how this mod's player crosses a map*, so that is precisely
where they will be when they reach for calibration, and arriving is safe: the
game enters an event on the action button, not on arrival. Home is now exempt
from the destination check; the hops still are not. The lesson is the general
one for this project -- a safety rule written from the outside refused the one
position the player was overwhelmingly likely to be in.

## Why the hotkeys were unreliable

Worth recording, because the symptom -- "the key works sometimes" -- sent two
rounds of fixes to the wrong place.

**The loop is far slower than a key press.** Each pass captures and analyses a
frame, so it runs about **four times a second**: measured against the live loop,
a median gap of 204 ms. A key tap lasts around 100 ms, so a press that starts
and ends between two polls never existed as far as the guide is concerned. A
100 ms tap fell inside a gap on **83 of 83 gaps**.

**GetAsyncKeyState's "pressed since last call" bit cannot fix it here.** That
low bit is exactly for slow polling, but Windows documents that another process
calling GetAsyncKeyState receives the bit instead -- and PCSX2 polls the
keyboard constantly. Two identical runs of the real loop with the same three
synthesised taps saw two, then none. A hotkey that works on a coin toss is
worse than one that plainly does not, because the player cannot tell which they
have.

**So keys are sampled on their own thread.** `hotkeys.KeyWatcher` reads the
physical state every 15 ms and counts presses; the loop collects them when it
gets round to it. Presses are counted rather than flagged, so two quick taps
are two questions and get two answers. Focus is deliberately not checked in
that thread -- enumerating windows sixty times a second is wasteful, and the
loop already drains the queue while the player is reading with their screen
reader. All the guide's keys share one thread and one watcher.

**Do not diagnose this class of fault by reasoning.** `menu_probe.py keys`
measures it: whether presses are seen, whether the game had focus, and how
often the loop actually looks.

## Adding a screen: the checklist

In the order that avoids wasted sessions. Steps 3 and 5 were skipped when Game
Level was added, and each cost a bug that only a live run revealed.

1. **Photograph it.** `positionscan` saves a screenshot beside every capture,
   and one picture settles the labels, the option count, and whether the menu is
   vertical or horizontal. Game Level answers to Left and Right; a press scan
   cueing "Down" would have captured three minutes of nothing.
2. **Find a marker** among the sprite names in the dynamic region. Prefer a name
   that means something -- `mc_da_5_lv_csr` is the level cursor -- over a byte
   signature, which is far weaker evidence.
3. **Check the marker against every other capture on disk, and every other
   screen's marker against this one.** Markers are *not* automatically mutually
   exclusive: the title screen's signature also matches on Game Level, and
   because Title is checked first it announced "New Game" over a difficulty
   chooser. `check` prints all of this.
   **And check the reverse: does an existing screen's marker match the new
   one?** Select Scenario was silent because Game Level's marker matched it,
   which no amount of looking at the new screen's own marker would have found.
   Before hunting for a marker at all, diff the new capture against the nearest
   mapped screen: if a region is identical between them, nothing in it can be a
   marker, and that one measurement saves an afternoon.
4. **Find the cursor**: `pressscan` for a wrapping menu driven by one repeated
   key, `positionscan` plus `fit` otherwise. Expect two copies -- a plain count
   in the screen's own allocation and a multiplied one in static memory. Wire
   both and cross-check them; one address cannot tell a correct read from a
   drifted one.
5. **Ask whether the HUD heuristic calls this screen gameplay.** If it does and
   the screen is not flagged `in_adventure`, menu reading is suspended and the
   screen is silent with no error anywhere. `check` says so in as many words.
6. **Verify on a transition you did not derive from**, then across an emulator
   restart if the address sits in the dynamic region.
7. **Say only what the screen says.** Game Level shows digits and never the
   words easy, normal or hard, so the mod says "Level 1".

## Dead ends -- do not re-tread

- **`0x00533FF0` and `0x00534030`** survived a five-snapshot search of the title
  screen, were stable, and were correct under every manual spot check. They
  disagreed with the screen on two autoscan samples. Not the cursor.
  Coincidence is cheap across a handful of snapshots of 31 MB.
- **`0x00AA1290`, `0x00AA56F0`** failed the same way.
- **`0x0034F000`** looked like a perfect screen enum -- a clean 32-bit word,
  the *only* survivor across title, main and Options, predicting 14 on Options
  exactly. It then failed the first transition it had not been derived from: it
  still read 14 after returning to the main menu. It is sticky, probably "last
  submenu entered". **Any candidate must be tested on a transition it was not
  derived from.**
- **Grouping frames by pixels** is exact on the title screen (same option 0.00
  apart, different options 21.41, tolerance 4.0) and **useless on the main
  menu**, whose clouds, characters and flavour text animate continuously. No
  region of the screen separated options; the best 10% band managed a ratio of
  1.16. A yellow-text mask was worse, at 0.5, because the carousel slides.
- **A uniform press schedule** is periodic, so every animation counter whose
  cycle divides the sample count fits it as well as the cursor does -- 32,840
  matches. Vary the press count instead.
- **Looking for menu and UI prose on the disc.** The Game Level screen's event
  name ("Mysterious Alien Warrior") and its instruction line are plainly
  readable in RAM, but neither appears **anywhere on the disc** as contiguous
  UTF-16LE or ASCII -- not in the executable, not in either AFS, searched end to
  end. They are stored packed and only become text once loaded. So the story
  corpus **cannot** be used to check them: it confirms cutscene dialogue and
  says nothing about UI prose. The two text sets are separate in storage as well
  as in content.
- **Pak names in RAM.** Only `zs2us_1.afs` and `zs2us_2.afs` appear. Individual
  paks are loaded by index; `Menu.pak` never appears as text.
- **Assuming a screen enum is a clean 32-bit word.** Filtering on that left zero
  candidates once the return-to-main constraint was added. The real identifier
  was a string, not an integer.
- **Assuming a text address is a display slot.** `0x00D1A782` was recorded as
  the Game Level event name from captures taken on event 00. It is the base of
  a name table, and on event 00 those are the same bytes. A slot and a table
  entry are only distinguishable on a *second* value -- so read an address on
  a screen where its contents ought to be different, not merely on a second
  visit to the same one.
- **Two screens cannot identify a screen.** A blind diff over title and main
  gave 210,051 candidates; adding Options gave 3,178; four screens with a
  return-visit constraint still left 552.

## Method

`source/tools/menu_probe.py`:

- `autoscan` -- captures RAM and screen together and groups samples by the
  label's pixels. Best on static screens; fails on animated ones.
- `pressscan` -- **preferred for animated screens.** Speaks a varying number of
  presses per sample, so the cursor follows a sequence nothing incidental
  reproduces. Does not assume the menu size; tries each and reports which fit.
- `labels ADDR` -- sweeps a menu and keeps a picture of each option, so the
  spoken table can be written from what was actually on screen. Cues each press
  rather than waiting to notice one.
- `check` -- **run this first when a screen is silent or names itself wrongly.**
  Prints which markers match, in the order detection considers them, what it
  settled on, what the cursor and its mirror read, and whether the HUD
  heuristic disagrees. Both faults found on Game Level were invisible from
  outside the mod and obvious in one line of this.
- `positionscan --screen=NAME --cues=Left,Right,Right` -- captures RAM and a
  screenshot after each **named** key press. The press scan assumes a menu that
  wraps and answers to one repeated key; this handles horizontal menus, menus
  with few entries, and menus reached only from inside a story event.
- `fit 2,1,2,3,2,1` -- given the positions **read back off those screenshots**,
  finds addresses constant per position, different between positions, and small
  enough to be an index. Read the positions off the pictures rather than
  assuming the presses landed: one missed press poisons the correlation while
  the run still looks clean. On Options this cut 39,101 raw matches to 67, of
  which 5 were real.
- `dryrun` -- runs the real guide loop with a recording speaker and prints every
  line spoken. The mod's whole output is speech, which otherwise cannot be
  checked without the player sitting at the controls.
- `find` / `snap` -- manual snapshot and sequence search.
- `watch ADDR...` -- poll addresses live to see which hold steady between
  presses.
- `recorrelate` -- re-analyse the last autoscan from disk. Capturing costs the
  player a live session; analysis must never require repeating it.

`source/tools/probe_voice.py` speaks cues through NVDA so the player stays in
the game. Instructions in a terminal do not work here: switching away loses the
menu to its attract demo, and a player who cannot see the screen has nothing to
time their presses by. Allow a **30 second lead** for the player to reach the
game after reading a message -- shorter leads produced three empty runs.

A 31 MB snapshot takes 0.7 s over PINE with no ill effect on PCSX2. Note that
`bt2/scan.py` warns that reading all of RAM starved the VM and correlated with
hangs; that concerns continuous polling during play, not one-off diagnostics.

`source/tools/extract_text.py` pulls the story corpus off the disc offline,
with no emulator and no player involved. See the Dragon Adventure TODO above.

Captures land in `reference/probe/` and extracted text in `reference/corpus/`,
both git-ignored. Game memory and game text must never be committed.

**The capture archive was pruned on 2026-09-06**, from 57 RAM dumps to six --
one per known screen: `auto0` (main menu), `press0` (Options), `pos0` (title),
`diff0` (Game Level), `library`, `main_after`. Every conclusion the deleted
ones supported is recorded above with its evidence, and each was verified
against the live game rather than against the dump.

What the six are kept *for* is the third step of the checklist below: checking
a new screen's marker against captures of other screens, which is how
`mc_da_5_lv_csr` was shown to be specific to Game Level. That needs one capture
per screen, not eighteen of the same one.

That is also how the claim was overturned. On 2026-09-07 seven captures of
Select Scenario were added -- `events0` and `posn0` to `posn5` -- and against
them `mc_da_5_lv_csr` at `0x00B1007B` is not specific to Game Level at all. The
six kept captures are what made the diff possible; keeping one per screen is
vindicated, and so is re-running step 3 whenever a screen is added rather than
trusting the answer it gave last time.

What is no longer possible is replaying `fit` or `recorrelate` over the old
multi-sample sets. If a derived address is ever doubted, re-derive it from a
fresh capture rather than trusting a dump that no longer exists. All 71
screenshots were kept: they cost almost nothing and are what make a capture
interpretable.

## Known gaps

- Dragon Library and every other submenu need cursor addresses.
- The Game Level cursor has not been checked across leaving the screen and
  coming back.
- **F12 reports the wrong event name on every event but the first**, because
  `0x00D1A782` is a table base rather than a display slot. See the Game Level
  section. Live in the shipped build.
- Other screens may also be misread as gameplay by the HUD detector, or shadow
  one another the way Title shadowed Game Level. Only the screens with captures
  on disk have been checked, and each new screen needs the same two questions
  asked of it.
- **The Select Scenario labels are true for the current unlock state only**, and
  break if a newly unlocked scenario is inserted rather than appended.
- The story event list is still unmapped, and it is the screen most likely to
  carry the current-event index. Whether `mc_da_2_text_off_l` or
  `mc_da_5_lv_csr` also match there is unknown -- there is no capture of it --
  so either marker could in principle shadow it, exactly as Game Level was
  shadowed. Capture it before trusting either.
- Ultimate Battle Z and the rest are not detected at all.
- **The stale-pointer gate is judged, not proven.** `0x008C6244` keeps its last
  value when nothing is on screen. Three checks make a wrong read unlikely, but
  no capture exists of a battle with no text box showing, which is the state
  they are meant to catch. If a stray line is ever heard, capture at that
  moment -- it cannot be manufactured offline.
- The **scenario synopses** are resident and readable but not spoken: the game
  renders them from a computed offset with no display copy, so they need the
  current-scenario index. Same missing piece as the event name.
- The subtitle block is relocated by shape, but only within
  `0x00C00000`-`0x00D00000`. If it ever lands outside that band the search
  misses it. Widening the band costs emulator time, so it should wait until a
  real miss is observed rather than being widened speculatively.
- Relocation has been tested against synthetic RAM only. Across one emulator
  restart the block did **not** move -- all ten lines still read at the recorded
  addresses -- so the search did not fire and remains unexercised against a real
  move. The block is evidently more stable than a single run's evidence
  suggested, which lowers the urgency but not the uncertainty.

## Fixed

- **"Unknown screen" on every transition.** No marker matches while one screen
  is unloading and the next has not loaded, so the announcer spoke on every
  navigation. `bt2/menus.py` now waits 1.5 seconds before saying it, which the
  gap never lasts. The standalone `menu_announcer.py` still has the old
  behaviour; it is a development tool.
- **A spurious first option on re-entry.** The cursor briefly reads 0 after a
  screen change. `bt2/menus.py` now requires a value to repeat across two polls
  before trusting it, so the half-written state is never spoken. Both the
  shipped module and the standalone announcer do this.
