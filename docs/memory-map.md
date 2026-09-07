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

**Story and tutorial text is the exception.** It is real UTF-16LE text in the
553 `TXT-US-*` files inside `ZS2US_1.AFS` -- 2,601 strings of cutscene
dialogue, narration and tutorials. Extractable offline from the ISO. Nothing
has been built on this yet; it is the obvious next feature.

## Screen identification

Each menu reuses the same memory for its own purposes, so a cursor address is
meaningless unless the right screen is up. `0x00AA12A8` is the main menu cursor,
but on Options the same byte reads 163 and on Dragon Library 208. Reading it
blindly names options at random.

Screens identify themselves: each loads its own table of sprite names into the
dynamic region around `0x00A00000`. Detection reads a short string at a fixed
address.

- **Main Menu** -- `mc_menu_lineanime` at `0x00AA15EC`
- **Options** -- `mc_icon_saveload` at `0x00AFCF85`
- **Dragon Library** -- `mc_musicprogram_0` at `0x00AB1FAF`
- **Title** -- no unique sprite name; identified by the 12-byte signature
  `01 80 00 00 00 00 00 C4 E1 06 53 53` at `0x00533D60`. **This signature is
  not exclusive**: it also matches on the Game Level screen. It is therefore
  treated as weak evidence -- see below.

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

- **Marker** -- `mc_da_5_lv_csr` at `0x00B1007B`. The screen's own cursor
  sprite. Absent at that address on both the main menu and Options.
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

- `0x00D1A782` -- the event name, "Mysterious Alien Warrior".
- `0x00D179C2` -- "Set the Match level to your strength. You can always adjust
  it later!"

Both are read on **F12**, not spoken automatically. They have been seen for
**one story event only**, and a different event's name is a different length and
may well sit elsewhere. Reading the wrong event name aloud would be exactly the
confident error this project treats as worse than silence, so it stays behind a
key press until it has been seen on more than one event.

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

The cost is one short read per frame during play, for the one screen flagged so
far. The pixel heuristic is left alone: it is load-bearing for navigation, and
this screen is a menu whatever it looks like.

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

## TODO: Dragon Adventure story subtitles

The largest remaining feature, and the reason the text work matters.

**What is known.** Story text exists as 2,601 real UTF-16LE strings in
`TXT-US-*` inside `ZS2US_1.AFS`, extractable offline. On-screen prose is
demonstrably readable from RAM. The subtitle system demonstrably works.

**What is not known.** How to tell which line is *currently* displayed. On a
menu the cursor gives that away free; in a cutscene lines advance on their own
and there is no cursor. A search of four menu captures found no stable pointer
to the displayed string, so the menus appear to render by index into a block.
Cutscenes may well differ, since they must show arbitrary lines in sequence.

**The corpus now exists.** `source/tools/extract_text.py` parses the disc's
ISO9660 directory and the AFS archive and pulls the story text out offline:
553 `TXT-US-*` files, 2,620 strings, **2,458 distinct lines**, landing in
`reference/corpus/` (git-ignored, like all game content). The count agrees with
the 2,601 counted independently before, which is the check that the parsing is
right rather than merely plausible.

Two things the extractor had to learn, both of which looked like success:
names in this archive are **not unique** -- 553 entries share 81 names -- so
keying on the name alone silently kept one file in seven; and the archives live
under `DATA/`, so a root-only directory search reports the disc is wrong when it
is not.

**How to settle it.** One capture session inside a Dragon Adventure cutscene:
capture RAM at several points as dialogue advances, then find the region whose
contents change to a *different known corpus string* each time. The extracted
corpus is the filter that makes this tractable -- "is this an actual line of
game dialogue" is far more selective than "did these bytes change". Re-extract
the corpus with `python extract_text.py`.

## Screens seen but not mapped

- **Dragon Library** -- detected only.
- **Ultimate Battle Z** -- not detected at all. The announcer correctly says
  "Unknown screen" there, which is the intended behaviour: naming a screen it
  cannot read would be worse than admitting it.

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

## Known gaps

- Dragon Library and every other submenu need cursor addresses.
- The Game Level cursor has not been checked across leaving the screen and
  coming back, and its two text addresses have been seen for one event only.
- Other screens may also be misread as gameplay by the HUD detector, or shadow
  one another the way Title shadowed Game Level. Only the screens with captures
  on disk have been checked, and each new screen needs the same two questions
  asked of it.
- Other Dragon Adventure screens -- the event list this one is reached from --
  are still unmapped. Whether they share `mc_da_5_lv_csr` is unknown, so the
  Game Level marker could in principle match one of them.
- Ultimate Battle Z and the rest are not detected at all.
- Nothing reads the 2,601 story strings yet.
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
