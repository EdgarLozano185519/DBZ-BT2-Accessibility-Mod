# Project status

Screen reader support for Dragon Ball Z: Budokai Tenkaichi 2, played in PCSX2.
Read this first when resuming. Details of every address live in
`docs/memory-map.md`.

Last updated: 2026-09-07.

## What works today

Menus speak through NVDA, driven by the game's own memory:

- **Title screen** -- New Game / Load Game.
- **Main Menu** -- all ten options, Dragon Adventure through Dragon Library.
- **Options** -- all five entries, Save and Load through Exit. The game keeps
  two copies of this cursor and both are read; if they ever disagree the mod
  stays silent rather than guess.
- **Game Level** -- the difficulty chooser inside Dragon Adventure, reached
  after picking a story event. Levels 1, 2 and 3, chosen with Left and Right.
  F12 reads the instruction line, the game's own text. It also reads an event
  name, and **that part is wrong** -- see Next steps.
- **Select Scenario** -- the Dragon Adventure scenario list: Saiyan Saga and
  Fateful Brothers on this save, chosen with Up and Down. Added 2026-09-07
  after the player reported it silent.
- **N and B choose a destination, G reports it, T teleports to it.** Teleport
  followed the story marker before, so a destination picked with N or B could
  be asked about but not travelled to. An explicit choice now decides where T
  goes; the guide never promotes its own starting guess to a decision.
- **G says how far away the destination is and which way to turn** while
  flying the world map. N and B step through the map's destinations and G
  reports whichever is picked. The guidance tones
  are panned by world direction, so they mean nothing without knowing your
  heading; G reads the player's own forward axis and answers as a turn plus a
  distance. On a key only, and it says when it cannot tell.
- **Screen detection** -- the announcer works out which screen is showing and
  picks the matching labels, or stays silent when it cannot.
- **Menu subtitles on F12** -- the character's spoken line for the highlighted
  main menu option, read as the game's own text rather than from a table we
  wrote. On a key press only, so it does not slow down browsing.
- **Story text speaks by itself.** Added 2026-09-07 and heard in play the same
  day. Cutscene dialogue and narration are announced as the game displays
  them, with no key press: the player advances the scene and each box is read.
  Save notices ("MEMORY CARD slot 1") are spoken too, at the player's request.
  Nothing is transcribed into a table -- `0x008C6244` is the game's own pointer
  to the text it is drawing, so this is not tied to English. See **Story text**
  in `docs/memory-map.md`.

Menu reading is **part of the guide app**. `bt2/menus.py` runs inside the guide
worker's main loop, at the one point where navigation guidance is suspended --
outside Dragon Adventure, which is exactly when the player is in a menu. The two
therefore never talk over one another. Press **F12** for the highlighted
option's spoken line. If the text block has moved since these notes were
written, the mod says "Looking for the subtitles.", finds it again, and carries
on.

`bt2/story.py` runs at the same point and for the same reason, but **only when
the menu reader does not recognise the screen** -- which is where a cutscene
lives. That gate is not incidental: the same pointer aims at a mapped menu's
own subtitle, so reading it everywhere would announce every subtitle
automatically as the player browsed, undoing the deliberate choice that made
F12 a key press.

## Releasing

`python source/tools/build_release.py --release=YYYY.MM.DD-rN` stamps
`BUILD-INFO.json` and regenerates `SHA256SUMS.txt`. `--check` verifies without
changing anything and is the fast way to ask whether the folder is coherent.

**It refuses to stamp if any runtime source is newer than the worker.** Editing
`bt2/*.py` changes nothing until the worker is rebuilt, and a release in that
state looks fine while behaving like the old code -- which happened during
development and cost a confused debugging session.

The manifest had gone stale because nothing regenerated it: by 2026-09-06, 26
recorded hashes no longer matched, 48 recorded files were gone, and
`bt2/menus.py` had never been in it at all. A manifest nobody regenerates fails
verification for the wrong reason and teaches people to ignore it.

Note that builds on this machine no longer emit the 44 `api-ms-win-*.dll`
compatibility stubs the September 5 release carried. They forward to the
Universal C Runtime, which ships inside Windows 10 and 11 -- the documented
requirement -- so their absence costs a supported system nothing.

## Running and building

**As a player.** Open `DBZ BT2 Guide.exe` and choose Open game, then Start
guide, exactly as before. Menus speak, and so does the story. Requirements are
unchanged:

- Windows 10/11 x64, .NET Framework 4.8
- PCSX2 with PINE enabled on port 28011 (the guide's Open game button does this)
- Their own PS2 BIOS and game dump: SLUS-21441, CRC FE961D28
- NVDA running, or Windows SAPI as the automatic fallback

**No Python, pip, or terminal is needed.** Everything ships inside the worker.

**Rebuilding after a source change.** The worker is a compiled bundle, so
editing `bt2/*.py` changes nothing until it is rebuilt:

    powershell -File source/tools/build_worker.ps1
    # then copy dist/guide-worker over the worker folder

    powershell -File source/tools/build_desktop.ps1
    # rebuilds the C# interface



Both verify the result is x64, because the bundled NVDA client is the 64-bit one
and a mismatch fails at runtime rather than at build time.

`build_announcer.ps1` builds a much smaller standalone menu reader (26 MB, no
numpy/scipy/Pillow) for testing menus without the full guide.

**From source, for development**, from `source/tools`:

    ..\..\.venv\Scripts\python.exe menu_announcer.py --seconds=120

## What the player actually does

Confirmed working in play, and worth not breaking:

1. **N and B** cycle the map's destinations, announced with distance and
   direction.
2. **G** says how far the chosen one is and which way to turn.
3. Pause PCSX2, press **T** to teleport there, unpause.
4. Try the action button. If nothing happens, cycle to the next point and
   repeat.

It is trial and error, because the story marker is a minimap object with no
coordinate-table entry and the projection that would fix that needs a scale
learned by flying. The player cannot fly and has said the trial-and-error loop
is acceptable. It has carried them through several story events.

**The single improvement that would remove the guesswork** remains teaching the
map scale by teleporting instead of flying -- see Also worth doing.

## The save file

As of 2026-09-06 the player has cleared several Dragon Adventure story events
and reached at least one further map, using the cycle-teleport-try loop above.
The save is no longer at the beginning, so work that was previously blocked on
having a second story event -- checking the event-name address holds across
events, or capturing a cutscene other than the opening -- is now possible and
should be re-offered rather than assumed blocked.

## Environment

- Game: `D:\games\roms\PS2\Dragon Ball Z - Budokai Tenkaichi 2 (USA) (En,Ja).iso`
  (SLUS-21441, CRC FE961D28).
- Emulator: PCSX2 2.9.32 at `D:\emulators\pcsx2`, config in `Documents\PCSX2`.
  **PINE is enabled** (`EnablePINE = true`, port 28011); a backup of the
  original `PCSX2.ini` sits beside it.
- Python 3.12.10 x64 with the pinned libraries, in `.venv`.
- The C# UI builds with the in-box .NET Framework compiler; no SDK needed.
- `source/tools/vendor/nvda/x64/nvdaControllerClient.dll` was restored from the
  shipped worker. The source tree cannot run without it.

Check the whole chain with `python pine_check.py`.

## Decisions waiting on the player

None of these are blocked on work. Each changes something the player already
uses, or trades one behaviour for another, so the choice is theirs rather than
the next session's to assume. Listed most consequential first.

**1. What should F12 do about the wrong event name?** It announces the first
event's name on every event, and has since it shipped. Two options: stop
announcing it now (one line, loses nothing that was ever true, but the key goes
quieter), or leave it wrong until the current-event index is found. Item 1
below has the detail. *Nothing will change here until this is answered.*

**2. Should story lines interrupt or queue?** They interrupt today, so the
player always hears the current box, but a long line is cut off if they advance
quickly. Queuing would read every line in full and fall behind a scene that is
still moving. Only the player can judge which is worse in play.

**3. Should the pointer replace the F12 subtitle machinery?** `0x008C6244`
reads the same subtitles that ten recorded addresses and a shape-based
relocation search read today -- and unlike them it did not move across three
PCSX2 runs. Replacing it deletes a moving part and the "Looking for the
subtitles." pause. But it changes something that works, so it should be
introduced as a change the player can judge and reject.

**4. Should a stray line be tolerated while the gate is unproven?** The
stale-pointer guard is judged, not proven -- see item 5. The alternative is to
read story text only after positively identifying a loaded scene file, which
would be stricter but would also silence save notices, which the player asked
for. Left permissive on purpose; revisit if a stray line is ever heard.

**5. Should this be stamped as a release?** The worker is rebuilt and deployed
but `BUILD-INFO.json` and `SHA256SUMS.txt` still describe the previous build.
Stamping is one command and is the player's call, not something to do because
the code changed.

**6. Should the 700 MB of captures be pruned?** `reference/probe` now holds
`cut0`-`cut7` at 31 MB each. The archive rule is one capture per screen; five
of the eight are distinct boxes and three are duplicates. Keeping them all
until the stale-pointer gate is settled is deliberate -- they are the evidence.

Older, still open: **pan the guidance tones by heading** and **speak the
heading itself**, both under Also worth doing, both deliberately not done
because they alter guidance the player has been flying with.

## Next steps, roughly in order

**When a screen is silent or names itself wrongly, run `python menu_probe.py
check` before theorising.** Both faults found on Game Level were invisible from
outside the mod and obvious in one line of that output, and both were reasoned
about wrongly first.

### 1. The event name on F12 is wrong, and shipped

`0x00D1A782` was recorded as the Game Level event name. It is not a display
slot -- it is entry 0 of a table of event names on a `0x40` granule,
and it reads "Mysterious Alien Warrior" on every event and even on Select
Scenario, where no event name is shown. The captures it was derived from were
all taken on event 00, where a table base and a display slot are the same
bytes.

So F12 announces the first event's name whatever the player is actually
playing. That is the confident error this project treats as worse than silence,
and it is in the shipped build.

Two ways out, and the second is better:

- **Stop announcing it** until it can be read correctly. One line. Loses
  nothing that was ever true.
- **Find the current-event index.** The story event list is the likeliest
  place for that index and needs mapping anyway.

**The table is not regular, so `0x00D1A782 + 0x40 * n` is not the fix** -- that
was recorded here and is wrong. Walking it offline
(`python story_probe.py names`) gives 230 entries in 240 granules: six names
are longer than 31 characters and continue into the following granule, and one
granule is empty. From the first long name onwards, arithmetic indexing reads a
continuation fragment -- "n!", "pe Baby", "use" -- and would speak it with the
same confidence as the bug it was meant to fix. The table has to be walked;
`story_probe.names` is the reference implementation and needs no player.

Not done unasked, because it changes a key the player already uses.

### 2. Verifications still owed

All cheap, all need the player at the controls. Ask before running any of
them -- see Testing with the player.

- **Game Level, leave and return.** Press Triangle to go back, re-pick the
  event, check it still tracks. Every cursor here is held to being tested on a
  transition it was not derived from; this one has not been. If it goes silent
  afterwards that is the two mirrors disagreeing, which is the design working.
- **The Select Scenario labels, when a third scenario unlocks.** The names are
  artwork, so they come from a table we wrote, indexed by position. The mod now
  announces **"Scenario 3, name not known."** for a row it has no name for, so
  a grown list is audible rather than silent. That announcement is the signal
  to re-check: appending is harmless, but a scenario *inserted* above Fateful
  Brothers would shift it and the mod would misname it confidently. Whether the
  game appends or inserts cannot be settled while the list has two entries.
  **If the player ever hears it, re-derive the labels rather than just adding
  one.**
- **The Dragon Library marker, in a second run.** It rests on a single visit,
  unlike the main menu's and Options'.

### 3. Map the remaining screens

- **The story event list**, inside Dragon Adventure -- the screen between
  Select Scenario and Game Level, where the player is still choosing blind.
  Now clearly the highest value of the three: it is both a silent screen and
  the likeliest home of the current-event index that fixes F12. Almost
  certainly needs `in_adventure=True`, since the HUD heuristic will call it
  gameplay too. **Capture it before trusting any marker near it** -- there is
  no capture of that screen, so whether the Select Scenario or Game Level
  marker also matches there is unknown, and that is exactly how Select Scenario
  came to be silent.
- **Dragon Library** -- detected, but cursor and labels both unknown.
- **Ultimate Battle Z and the rest** -- not detected at all, so each needs a
  marker found before a cursor is worth looking for.

Follow **Adding a screen** in `docs/memory-map.md`; it is a checklist because
this session skipped two of its steps and shipped two bugs.

### 4. Teach the map scale by teleporting, not flying

**The one change that would most improve play.** The story objective is a
minimap marker with no coordinate-table entry, so reaching it means teleporting
to table points one at a time and trying the action button. That works and the
player accepts it, but it is guesswork.

The calibrator learns from pairs of world movement and screen movement and does
not care how the player moved. Teleport is movement the guide controls, so a
few short teleports in known directions should teach it the scale without any
flying. The Jacobian is saved per map profile, so it is a one-time cost per
map, after which T could go straight to the story marker.

Needs a pause and unpause from the player per step -- four or so per map --
unless the pause can be driven programmatically, which is worth checking first.

### 5. Finish the story reader

The reader ships and works. What is left is one unproven guard and three
features the same discovery has made cheap.

**The stale-pointer gate is judged, not proven.** `0x008C6244` is not cleared
when nothing is on screen: leaving a cutscene it goes on aiming at the last
thing drawn. Three guards cover every case actually observed -- text that does
not decode is refused, text using characters outside the story alphabet is
refused, and move-list markup is refused. But **no capture has ever been taken
of a battle with no text box showing**, which is the state the gate is meant to
catch. If a stray line is ever heard, stop and capture at that moment:

    python story_probe.py capture stray --boxes=2

That is the single piece of evidence still missing, and it cannot be
manufactured offline.

**Three features the pointer makes cheap**, none of them started:

- **Dragon Library and Select Scenario prose.** Both are unmapped screens whose
  subtitle the pointer already reads correctly in captures. Reading them needs
  no new addresses at all.
- **The 26 scenario synopses**, resident at `0x00D1E3C0`-`0x00D24D40` whenever
  Dragon Adventure is open. These are the intros to each Dragon Adventure
  scenario, sitting in RAM at known addresses -- but the game renders them from
  a computed offset with no display copy, so speaking the *highlighted* one
  needs the current-scenario index, which is the same missing piece as the
  event name in item 1.
- **Replacing the F12 subtitle machinery.** One pointer supersedes the ten
  recorded subtitle addresses and the shape-based relocation search, and does
  not move between runs where they do. See **Decisions waiting on the player**;
  this changes behaviour that already works, so it is not done unasked.

### Also worth doing

- **Partly confirmed in play, 2026-09-06.** Loading a new map now updates the
  destinations correctly, and the player is progressing through the story with
  it. Two paths remain unproven and should not be described as working: the
  **two-table refusal**, since it is unknown whether a second table has ever
  been resident on this save, and the **in-place marker change**, where a story
  event rearranges markers without the map changing -- that announces
  "Destinations changed" and has not been heard yet. Both fail safe.



- **The pause requirement is the remaining friction in teleport.** It is a real
  safety property -- PINE writes race the emulator's CPU thread -- but it means
  the one feature that does not need sight still needs the player to pause
  PCSX2 by hand and press T again. **PINE cannot do it**: the opcode table in
  `pine_client.py` has read, write, save-state, load-state and status, and no
  pause -- checked 2026-09-07. The remaining route is a synthesised key press
  to the focused emulator window; PCSX2 binds `TogglePause` to Space on this
  machine, and `pine.status()` returns 1 when paused, so the guide could
  *verify* the pause took rather than assume it. That verification is what
  makes it worth trying.
- **Flying is the thing the player cannot do.** Movement is unpredictable
  without sight, so teleport is not a convenience here; it is the primary way
  to travel. Weight future work accordingly.

- **Pan the guidance tones by heading, not by world direction.** G answers the
  question on demand, but the continuous cue is still world-absolute: stereo
  left means west, not your left. The player's forward axis is now available
  and `guide.py` already does exactly this for local surfaces, so the change is
  small. It was left out deliberately -- it alters guidance the player has been
  flying with, and should be introduced as something they can judge and reject
  rather than arriving unannounced.
- **Speak the heading itself** ("facing northwest"), for orienting with no
  objective selected. Cheap once the facing is read.

### Smaller, optional

- The standalone `menu_announcer.py` still says "Unknown screen" on every screen
  transition, and does not have the mirror cross-check or the named-marker
  precedence. It also knows only four screens: neither Game Level nor Select
  Scenario is in its table, so it is silent on both. The shipped
  `bt2/menus.py` has all of it. It is a development tool, so this matters only
  during a long probing session -- but it no longer reflects how the mod
  behaves, and the gap is widening rather than holding steady.
- Nothing checks read text against the extracted corpus at runtime, and that
  is now a settled decision rather than a gap. The corpus is a **search** tool
  rather than a runtime dependency -- the ten main menu subtitle lines score zero against it,
  so a runtime corpus match would reject real text and tie the mod to English.
  What `bt2/story.py` does instead is check the *alphabet*: ASCII, newline and
  General Punctuation, which is every character the 2,601 boxes use. That
  refuses garbage and move-list glyphs without knowing a single word.

## Recently finished

### 2026-09-07: the story speaks

- **`0x008C6244` is a pointer to the text the game is drawing.** Found from
  eight captures through one cutscene -- the only address in 31 MB whose value
  tracked the text box. Confirmed against nine captures it was not derived
  from, then verified live on two later cutscenes loaded at a *different base*,
  each matched against a screenshot taken at the same moment. It reads menu
  subtitles, Game Level's instruction line, and Dragon Library and Select
  Scenario prose as well as cutscene dialogue. It did not move across three
  PCSX2 runs spanning two days.
- **`bt2/story.py` ships it**, with `test_story.py` covering it in 31 offline
  checks that need no emulator: nine against real captures whose expected text
  was read off the screenshots beside them, the rest synthetic RAM for the
  refusals, which are the cases that matter most.
- **Two byte-sized candidates were found first and refuted.** They matched the
  box sequence across all eight captures and were the only two bytes in 31 MB
  to do so; on the next scene they disagreed with each other and with the
  screen, and one moved 7 to 0 between two reads seconds apart. Had the rule
  about verifying on an underived transition not been followed, a confident
  lie would have shipped. This is the clearest example yet of why that rule
  exists.
- **The disc text format is decoded**, so `extract_text.py` parses rather than
  scrapes: all 553 files, 2,601 text boxes, matching the count reached
  independently before. Output is `story_scenes.json`, keyed by scene with one
  entry per slot. The old regex split every line containing a typographic
  apostrophe into fragments that would have matched nothing in RAM.
- **`extract_text.py` had never run without `--iso`**: it asked `bt2.profiles`
  for the disc path, which holds map profiles and has no such key. It now reads
  the path the desktop app stores.
- **`story_probe.py` is new** -- `capture` records RAM and a screenshot each
  time the text box changes while the player simply plays, `scan` and `compare`
  sort addresses into display slots and resident blocks, `names` walks the
  event-name table, `follow` drives the shipped reader from a terminal.
- **A latent crash in `speech.py` was found and fixed.** The echo to stdout
  could raise `UnicodeEncodeError` on any character cp1252 cannot encode, and
  that killed the whole guide loop twice in one play session. Never specific to
  story text; the feature merely fed the log new material.
- **A correction to a documented plan.** The event-name table is *not* regular,
  so `0x00D1A782 + 0x40 * n` was never the fix it was recorded as. Six names
  overflow their granule and one granule is empty, so arithmetic indexing reads
  fragments. It has to be walked.
- **The 26 scenario synopses were located**, resident at
  `0x00D1E3C0`-`0x00D24D40` whenever Dragon Adventure is open and nowhere else.
  Not yet speakable: the game renders them from a computed offset with no
  display copy, so they need the current-scenario index.

### Earlier

- **Select Scenario speaks.** It was silent because Game Level's marker matched
  it: the two screens share their dynamic allocation **byte for byte**, so no
  marker in that region can separate them. Both markers moved to the per-screen
  sprite-name table around `0x00D52000`, which does differ, and each now matches
  its own screen and nothing else across all thirteen captures. The cursor was
  found from six cued captures with the positions read back off the
  screenshots, agrees in two separate allocations, and agrees with a seventh
  capture taken before the scan began. Confirmed live and through `dryrun`.
- **An unnamed scenario now says so.** This is the one menu whose length grows
  with play, so an index off the end of the table means the player has unlocked
  something, not that a read went wrong. It says which row it is and admits the
  name is missing, which also serves as the tripwire for the insertion case
  that would otherwise misname silently.
- **A caution that came with it.** The scenario list has two entries, so the
  press schedule only distinguishes parity and is weak evidence on its own.
  What makes the four survivors believable is that they also differ on the Game
  Level capture and are small enough to be an index. Worth re-checking when a
  third scenario unlocks.

- **The story corpus is now parsed, not scraped.** `extract_text.py` reads each
  `TXT-US-*` file by its own self-describing format -- a slot count, an offset
  table, then BOM-prefixed UTF-16LE boxes. All 553 files parse, giving 2,601
  text boxes, which is exactly the count reached independently before. The
  previous regex over printable ASCII produced 2,458 "lines" that looked right
  but split every line containing a typographic apostrophe into fragments
  matching nothing in RAM. Output is now `story_scenes.json`, keyed by scene
  with one entry per slot, so a box carries its position in the scene.
- **`extract_text.py` also ran only with `--iso`.** Without it, it asked
  `bt2.profiles` for the disc path, which holds map and area profiles and has
  no such key, so the documented bare `python extract_text.py` always raised.
  It now reads the path the desktop app stores.
- **`story_probe.py` is new**, and does the analysis the capture session needs:
  `scan` reports which story text is resident in a capture and which scene it
  belongs to, `compare` sorts addresses into display slots and resident blocks
  across several captures, `names` walks the event-name table, and `live` reads
  the resident pool through PINE.
- **A negative worth knowing:** the Game Level screen's event name and
  instruction line are nowhere on the disc as plain text, so the corpus cannot
  validate them. Cutscene lines can be checked against it; UI prose cannot.

- **Two detection bugs found by the first live run of Game Level**, which
  announced nothing at all. The HUD detector reads that screen as gameplay, so
  menu reading was suspended there; a menu marker now overrules the heuristic.
  Underneath that sat a worse one: the title screen's byte signature also
  matches on Game Level, and being checked first it announced "New Game" over a
  difficulty chooser. Named markers now outrank raw signatures, and two names
  matching means the mod admits it does not know.
- **Game Level speaks.** Found from a live session on the screen itself: a
  screenshot gave the labels and layout, the screen's own cursor sprite gave a
  marker, and six captures at visually confirmed positions gave the cursor. Two
  copies of it, cross-checked, as with Options. Still owes a
  leave-and-return check.

- **Options speaks, all five entries.** Found by a press scan that matched five
  options and nothing else, then confirmed on a re-entry it was not derived
  from, then again across an emulator restart. Its marker is no longer a
  single-visit guess: it has now held across two runs and four visits.

- **The subtitle block is found by shape, not by address.** The ten recorded
  addresses came from one PCSX2 run and the block moves between runs, which
  left F12 dead until the next rebuild. When a read stops looking like text the
  mod now searches a narrow band for ten readable lines at the known spacing
  and remembers the offset. No game text is hardcoded, so it is not tied to
  English. Costs nothing on the happy path. **Tested against synthetic RAM
  only** -- across one emulator restart the block did not move, so the search
  never fired and has still not met a real move.

- **The two announcement flaws are fixed** in the shipped path. "Unknown
  screen" now waits 1.5 seconds before speaking, so the gap between one screen
  unloading and the next loading passes silently. The cursor must read the same
  value twice before it is trusted, so the spurious first option on re-entering
  a screen is gone.
- **The announcer is integrated.** `bt2/menus.py` runs inside the guide
  worker's loop rather than as a separate script, and the worker in `worker/`
  is built from it.

## Testing with the player

These are the player's stated preferences. They are not politeness; each one
came from a test that produced a confidently wrong answer.

- **Ask before running any test, and wait for a yes.** Do not start a live run
  because it seems obviously useful.
- **Anything involving a key press must either speak a countdown through NVDA,
  or focus the game window itself first.** Use
  `bt2.windows.focus_game_window()`, which brings the render window forward and
  *verifies* it got there. Without focus the guide refuses hotkeys on purpose,
  so a test run against an unfocused window measures nothing -- three
  synthesised presses were once reported as "not detected" when they had simply
  been refused as designed.
- **Say plainly whether a test needs the player at the controls.** Synthesised
  key presses and read-only memory checks do not; anything asking them to fly,
  pause or press a button does.
- **A synthesised key press goes to whichever window has focus.** If that is the
  game, the game receives it. Say so before running one.

## Working notes

- **Verify on a transition you did not derive from.** `0x0034F000` looked like a
  perfect screen enum and failed the first fresh transition. Several cursor
  candidates did the same. A candidate that fits the data it was found in has
  proved nothing. The strongest example is the story reader: two bytes matched
  an eight-capture sequence and were the *only* two in 31 MB to do so, which
  felt like proof and was not. On the next scene they disagreed with the screen
  and with each other.
- **Measure before planning around a number.** A whole capture protocol --
  pausing the emulator, coordinating each shot with the player -- was designed
  around an estimate that a 31 MB read takes ten seconds. It takes 0.6. The
  estimate came from scaling a sentence in these notes rather than running one
  command. Cheap facts should be measured, not inferred, especially when the
  inference is what makes the work look expensive.
- **A number in these notes is evidence, not truth.** The event-name table was
  recorded here as regular and 392 entries; it is neither. Re-derive before
  building on a recorded figure.
- **Capture RAM and the screen together.** Pairing them is what made results
  trustworthy; snapshot-only searches produced confident wrong answers.
- **Speak instructions, do not print them.** The player cannot read a terminal
  while playing, and leaving the game loses the menu to its attract demo. Allow
  a 30 second lead for them to reach the game after reading a message.
- **Never commit game content.** `reference/` and `*.bin` are git-ignored.
  Captured RAM, extracted text and screenshots stay local.
- The user is blind and uses NVDA. Silence is indistinguishable from success, so
  the mod must say when it cannot help -- and must never name an option it is
  not sure of.
