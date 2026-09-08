# Project status

Screen reader support for Dragon Ball Z: Budokai Tenkaichi 2, played in PCSX2.
Read this first when resuming. Details of every address live in
`docs/memory-map.md`.

Last updated: 2026-09-08.

## What works today

Menus speak through NVDA, driven by the game's own memory:

- **Title screen** -- New Game / Load Game. Its marker is a raw byte
  signature, and as of 2026-09-08 it has been caught on three screens that
  were not the title. It is now refused whenever the game is drawing text,
  which it never does on the title capture and always did on the three.
- **Main Menu** -- all ten options, Dragon Adventure through Dragon Library.
  It stopped being recognised on 2026-09-07 and read out the option subtitles
  instead. The cause is now known and measured: a Select Scenario marker that
  is still resident after Dragon Adventure has been left, colliding with it.
  A marker known to outlive its screen now loses to one that is not.
  **Not yet confirmed in play.**
- **Options** -- all five entries, Save and Load through Exit. The game keeps
  two copies of this cursor and both are read; if they ever disagree the mod
  stays silent rather than guess.
- **Game Level** -- the difficulty chooser inside Dragon Adventure, reached
  after picking a story event. Levels 1, 2 and 3, chosen with Left and Right.
  F12 reads the instruction line, the game's own text. It used to read an event
  name as well, which was the first event's name whatever the player had
  chosen; that is gone as of 2026-09-07.
- **Select Scenario** -- the Dragon Adventure scenario list, chosen with Up and
  Down. Five scenarios on this save; **all twenty-five on the disc are named**,
  walked out of the game's own name table. Names are keyed by the game's own
  scenario numbers, read from `0x00B05308`, so unlocking a scenario neither
  shifts the others nor leaves the new one unnamed. Proven by a real unlock the
  same day, and the reason this part of the guide can be handed to someone else.
  See *When you unlock a scenario* below.
- **Character Select** -- the two-player grid in Dueling, added 2026-09-08.
  Each player's highlighted character is spoken as their cursor moves, in
  either axis. The names are read from the text the game is drawing, through
  two pointers of the kind the story reader uses -- one per name panel -- so
  there is no cursor address and no table of names: nothing was transcribed
  and nothing is tied to English. **Player 1 was heard in play the same day**,
  forty names in the log. Player 2 went silent in play, was traced to the
  second pointer, and is verified against seven screenshots; **not yet heard
  through the guide app.** The first move on player 2's side is announced as
  "Player 2: name", later ones bare. Before this the mod announced
  **"New Game"** over the grid, by the title screen's weak signature -- the
  same fault Game Level had.
- **Tournament Character Select** -- Dragon Tournament's entry screen, added
  2026-09-08 after it was silent in play. Same portraits, one name panel,
  read through the first pointer only. Its marker is the same sprite at a
  different address, seen on one visit. The log for that session also shows
  the mod flickering between "Unknown screen" and "New Game" there, which is
  what closed the title-marker hole above. **Heard in play the same day**:
  the log holds the screen's name and four fighters after it.
- **C teaches this map's scale by teleporting, so T can reach the story
  marker.** Added and **confirmed in play 2026-09-07**, twice on the Blue
  landmass map, after which T reached the story objective. Six short commanded
  hops, each announced -- pause, "Moved", unpause -- ending exactly where it
  started. `bt2/mapcal.py`; `test_mapcal.py` covers it in 30 offline checks
  that need no emulator.
- **The story marker is the last entry in the N and B cycle**, on a calibrated
  map. Added 2026-09-07 after the player asked, in play, whether it was --
  which it should have been from the start. Before this, one press of N locked
  T to a table point until the map changed, so calibrating and then browsing
  silently took the story marker away again.
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
  picks the matching labels, or stays silent when it cannot. Two screens
  matching at once means it does not know and says so; a marker known to
  outlive its screen loses to one that is not; and when a screen cannot be
  named or its cursor cannot be trusted, that is written to the log with the
  reason.
- **F12 says the prose on screen, on every screen.** The character's spoken
  line for the highlighted main menu option, the Game Level instruction line,
  Dragon Library and Select Scenario prose, a cutscene box -- all of it, read as
  the game's own text rather than from a table we wrote. On a key press only, so
  it does not slow down browsing. Rebuilt 2026-09-07: it was polled below the
  point where an unrecognised screen returned early, so on any screen the mod
  could not name -- which is most of them -- **pressing it did nothing at all**,
  not even say so.
- **Story text speaks by itself.** Added 2026-09-07 and heard in play the same
  day. Cutscene dialogue and narration are announced as the game displays
  them, with no key press: the player advances the scene and each box is read.
  Nothing is transcribed into a table -- `0x008C6244` is the game's own pointer
  to the text it is drawing, so this is not tied to English. See **Story text**
  in `docs/memory-map.md`.
  **Only scene text is announced**, which is what keeps unmapped menus quiet;
  a save notice is no longer spoken by itself and is read on F12 instead. That
  was the player's call -- see the paragraph on save notices below.

Menu reading is **part of the guide app**. `bt2/menus.py` runs inside the guide
worker's main loop, at the one point where navigation guidance is suspended --
outside Dragon Adventure, which is exactly when the player is in a menu. The two
therefore never talk over one another. Press **F12** for the prose on screen. If
a block has moved since these notes were written, the mod says "Looking for the
subtitles." or "Looking for the menu.", finds it again, and carries on.

`bt2/story.py` runs at the same point and for the same reason, and there are
**two rules between them**, because one was not enough.

The first: `MenuReader.reads_options()` is true when the mod has named the
screen, that screen has a mapped cursor, and the evidence that named it also
says where that cursor is. Where it is true the option is spoken and the story
reader stays quiet.

The second: **the story reader speaks only out of the scene text buffer.** The
first rule left it reading menus the mod had not been taught -- announcing the
highlighted option's flavour text on the Item Shop or the story event list --
which the player asked to be rid of. A cutscene's text is loaded into a buffer
around `0x0109F000`; a menu's prose lives in the menu's own allocation, three
and a half megabytes below the nearest scene box in every capture on disk. So
an unmapped menu is now silent while browsing.

**F12 is outside both rules** and reads whatever is on screen, mapped or not,
named or not. That is the whole arrangement: menus are read on request, the
story is read as it happens.

**Save notices go with the menus, and that is the player's decision**, taken
2026-09-07 when the trade-off was put to them. "MEMORY CARD slot 1" is not a
scene box and has probably stopped being announced; F12 reads it like any other
screen text. Not a gap to close -- but if a refused line ever turns up in the
log beside a save the player expected to hear, its address is right there and
the rule can be widened by measurement.

## When you unlock a scenario

**Nothing. It just reads out.** All twenty-five scenario names on the disc ship
with the guide, keyed by the game's own scenario numbers, so a newly unlocked
scenario is named the first time it appears and the rest are undisturbed.

If a row ever does say **"Scenario 5 of 6, name not known."**, that means the
game used a number this list does not have, which would be worth reporting. The
steps below are how a name gets added, and should no longer be needed.

To name the new one, with the guide app closed and PCSX2 on the Select Scenario
screen:

    cd source/tools
    ..\..\.venv\Scripts\python.exe menu_probe.py rowscan B0536C B05370 --seconds=60

It counts down aloud, then says "move through every row". Press Down, pause a
second or two, and go round the list once. It photographs each row; the new
name is read off the picture of the row that went unnamed, and added as one
line to `labels_by_id` in `bt2/menus.py`, keyed by its scenario number.

**Why this should never be needed:** every scenario name on the disc already
ships, walked out of the game's own table. Hearing "name not known" would mean
the game used a scenario number that table does not cover, which would be worth
knowing about. Item 3 under Next steps has the detail.

## Releasing

`python source/tools/build_release.py --release=YYYY.MM.DD-rN` stamps
`BUILD-INFO.json` and regenerates `SHA256SUMS.txt`. `--check` verifies without
changing anything and is the fast way to ask whether the folder is coherent.

Two more things per release, both learned on 2026-09-08. Bump `WORKER_VERSION`
in `guide_host.py` *before* rebuilding the worker -- it is what the log's
first line and the spoken greeting report, and it had sat at 2026.09.05-r4
through a later stamp. And the release zip is the manifest's files plus
`SHA256SUMS.txt`, built by `source/tools/make_release_zip.py` into the repo
root as `DBZ-BT2-Guide-<release>.zip`; zips are git-ignored so the GitHub
release stays separate from the source history.

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

**The offline suites need no emulator, no game and no player**, and are the
first thing to run after changing any of this:

    ..\..\.venv\Scripts\python.exe test_menus.py    # 223 checks, 27 captures
    ..\..\.venv\Scripts\python.exe test_story.py    # 44 checks
    ..\..\.venv\Scripts\python.exe test_mapcal.py   # 30 checks

**From source, for development**, from `source/tools`:

    ..\..\.venv\Scripts\python.exe menu_announcer.py --seconds=120

## What the player actually does

Confirmed working in play, and worth not breaking. **This changed on
2026-09-07** -- the trial-and-error loop below is now the fallback rather than
the main route.

On a calibrated map:

1. Press **C** once per map. Six announced hops, ending exactly where it
   started. It says "calibrated" and the scale is saved.
2. **N** until "the story marker" -- it is the last entry in the cycle.
3. Pause PCSX2, press **T**, unpause. You are on it.
4. Action button.

Before **C** has run on a map, or if it refuses, the older loop still works and
is what carried the player through several story events:

1. **N and B** cycle the map's destinations, announced with distance and
   direction.
2. **G** says how far the chosen one is and which way to turn.
3. Pause PCSX2, press **T** to teleport there, unpause.
4. Try the action button. If nothing happens, cycle to the next point and
   repeat.

That one is trial and error, because the story marker is a minimap object with
no coordinate-table entry and converting it needs a scale that used to be
learnable only by flying. The player cannot fly and had said the trial-and-error
loop was acceptable.

**The guesswork is what C removes.** It has been run twice in play on the Blue
landmass map, and T reached the story marker from it. Whether it holds on a map
other than that one is the open question -- see item 7 under Next steps.

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

**Every session the player plays leaves a transcript**, in
`%LOCALAPPDATA%\DBZ BT2 Guide\logs\desktop-<timestamp>.log`. It holds every
line the guide spoke, in order, plus anything the worker printed without
speaking. That is the closest thing to a recording of a play session, it
needs nothing set up in advance, and it is the first place to look when the
player reports something. The 2026-09-07 menu fault was diagnosed from it
entirely: the logs show "Main Menu" announced only in sessions that reached
it from the title screen, never in one that had been inside Dragon Adventure,
and they show that F12 had never produced a single line in any session.
`bt2.speech.note` writes to it without speaking, which is where screen
detection now records why it stayed silent.

**Three things about running the guide from a terminal**, all learned the hard
way on 2026-09-07 and all cheap to trip over again:

- **PINE serves one client at a time.** A second connection does not fail
  cleanly, it *times out* -- so while the guide is running, `pine_check.py` and
  any probe script will hang rather than say why. Stop the guide before reading
  memory from a script.
- **`guide_host.py` treats a closed stdin as "the desktop app went away".** It
  is right to: that is how the UI signals shutdown. But a background process
  has no stdin, so launching it from a script makes it print "Guide stopped."
  and exit within a second. To run the guide headless, call
  `waiting_guide("objective", speaker=Speaker())` directly and set
  `BT2_DESKTOP_UI=1` so the hotkeys still require the game window to have
  focus -- otherwise typing in a terminal fires teleports.
- **The worker cannot be deployed while the guide app is open.** Windows locks
  the running executable, so `Copy-Item dist\guide-worker\* worker` fails on
  `guide-worker.exe` and a few DLLs while quietly succeeding on the rest. It
  looks like a partial failure and is actually harmless -- the support files
  are identical between builds -- but **the player keeps running the old
  worker**, which cost a whole round trip here: a fix was reported as deployed,
  tested, and found not to be in the build. Close the app first, and confirm
  afterwards with `build_release.py`'s `stale_sources()` or by hashing
  `dist\guide-worker` against `worker`.

To hear what the mod would say without starting the app at all, use
`python menu_probe.py dryrun --seconds=8`: it drives the real reader against
the live game and echoes every line. That is also the quickest check that a
change reached the code the player runs.

## Decisions waiting on the player

None of these are blocked on work. Each changes something the player already
uses, or trades one behaviour for another, so the choice is theirs rather than
the next session's to assume. Listed most consequential first.

**1. Should story lines interrupt or queue?** They interrupt today, so the
player always hears the current box, but a long line is cut off if they advance
quickly. Queuing would read every line in full and fall behind a scene that is
still moving. Only the player can judge which is worse in play.

**2. Should the pointer replace the F12 subtitle machinery outright?**
`0x008C6244` is now the *fallback* for F12, so the key works everywhere; the ten
recorded addresses are still tried first, because on a mapped screen they read
the line belonging to the highlighted row rather than whatever is on screen.
Deleting them would remove a moving part and the "Looking for the subtitles."
pause. It would also be a change to something that works, so it is still the
player's call rather than the next session's.

**3. Should a stray line be tolerated while the gate is unproven?** The
stale-pointer guard is judged, not proven -- see item 8. The scene-buffer rule
above has incidentally made this much stricter: a stale pointer left aiming at
menu text after a scene ends is now refused by address as well as by content.
The remaining exposure is a stale pointer still inside the scene buffer.

**4. ~~Should this be stamped as a release?~~** Done: 2026.09.08-r1, at the
player's request, with a release zip built beside it. The spoken version in
`guide_host.py` had been left at 2026.09.05-r4 through the 09.07 stamp and is
bumped with this one; the log's first line is what shows which build a player
is actually running, so it should move with every stamp.

**5. Should the captures be pruned?** `reference/probe` is now **892 MB**, 27
snapshots at 31 MB each, and it is git-ignored so it costs nothing but disk.
The archive rule is one capture per screen, and two groups break it on purpose:
`cut0`-`cut7`, of which three are duplicate boxes, kept until the stale-pointer
gate is settled; and the thirteen scenario-list captures, which are the evidence
for `0x00B05308` and for every name on that screen. The scenario ones have
earned their place. The cutscene duplicates are the ones to drop first.

**6. Should OCR be tried for the screens that are still silent?** Raised by the
player 2026-09-07. It would not have helped the scenario list -- that was an
identity problem, and memory answered it -- but the unmapped menus (Item Shop,
Data Center, Ultimate Battle Z, Evolution Z, the story event list) are silent
precisely because their labels are artwork. Notes on engines, costs and the
risk of confident misreadings are under *Reading labels that are artwork*
below. Nothing is installed, and no OCR has been attempted yet.

Older, still open: **pan the guidance tones by heading** and **speak the
heading itself**, both under Also worth doing, both deliberately not done
because they alter guidance the player has been flying with.

## Next steps, roughly in order

**When a screen is silent or names itself wrongly, run `python menu_probe.py
check` before theorising.** Both faults found on Game Level were invisible from
outside the mod and obvious in one line of that output, and both were reasoned
about wrongly first.

### 1. The Select Scenario marker is refuted, and needs replacing

**The cause of the main menu going quiet is now known**, and it was not the
main menu. From `desktop-20260907-170425-949.log`, 168 times over:

    menus: several screens matched at once, so none was named
           -- Main Menu, Select Scenario

`mc_da_2_text_off_l` at `0x00D53440` is **still resident after Dragon Adventure
has been left**. On the main menu it collided with the real marker and
detection refused to name either, which is the safety rule working on bad
input; the story reader then read out the subtitle of every option the player
browsed past. On Options, where the main menu's marker had gone, the leftover
matched alone and the guide announced **"Select Scenario" over the Options
screen**.

Every capture on disk is clean, and that is the trap worth remembering: the
non-Adventure captures were all taken in sessions that had never entered Dragon
Adventure, so "absent on the main menu" was never evidence of anything. **A
marker's exclusivity is only as good as the routes the captures took.**

**The mitigation is in.** A marker known to outlive its screen loses to one
that is not, and which markers those are is recorded from what has been seen.
Both errors above are covered, and `test_menus.py` holds them.

**The repair is not.** By this project's own standard `0x00D53440` is now a
retired address -- it has been seen naming a screen that was not up, exactly as
`0x00B1007B` was when it matched both Dragon Adventure screens. It is kept only
because it is still the one address that separates Select Scenario from Game
Level. Replacing it needs **a capture of the main menu taken after Dragon
Adventure has been left**, which has never existed:

    python menu_probe.py snap mainmenu_after --full

Stop the guide first -- PINE serves one client at a time. That one file shows
which Dragon Adventure addresses are stale on the main menu and which are not,
and a marker chosen from the survivors would be exclusive on the evidence
rather than by precedence.

**The relocation search built for the other explanation has never fired**, in
any session. It is kept because the reasoning stands and it costs nothing until
it is needed, but it was insurance and not the fix.

### 2. Select Scenario reads its cursor once, and no second copy exists

**Settled 2026-09-07, offline.** Every other readable screen here reads its
cursor twice over and stays silent if the copies disagree. This one cannot,
and that is now measured rather than assumed.

`0x00D53625` was the cursor from the day this screen was mapped and is not an
index at all -- it reads 1 for two different rows. It survived six cued
presses, three captures and a held-out seventh because the list had **two**
entries, where position and parity are the same thing. `0x00B0536C`, until then
the cross-check, is the real index, and the pair was never a pair.

The search for a genuine second copy needed the player only until the
four-entry captures existed. Run over all **twelve** scenario captures at once
-- four rows of the four-entry list, seven of the two-entry, one of the
three-entry, each with the row read off its screenshot -- asking for any
address that tracks the row, at any scale, or that counts up by one per row
from any base:

    only 0x00B0536C tracks the row in all twelve captures

Twelve offset-ramps fit the four-entry list and every one of them fails on the
two- and three-entry captures. **There is no second copy in EE RAM**, at least
not at the moments captured; scratchpad and VU memory are outside what PINE
reads here and have not been looked at.

**What stands in for it.** The row is bounded by the length at `0x00B05370`,
and the scenario number it resolves to must be one the mod has a name for. A
drifted or half-written read therefore lands out of range, or on a number with
no name, and says "name not known" rather than naming the wrong scenario. That
is weaker than two copies agreeing -- it cannot catch a read that lands on a
*different valid* row -- and it is the reason this screen is worth re-checking
first if it ever misbehaves again.

### 3. Every scenario is named already -- done, but check the last three

**The handoff question is answered: a player who unlocks a scenario hears its
name, with no tools, no editing and nobody who has Claude.** All twenty-five
scenario names now ship with the guide.

The route was not the obvious one. The names *are* in RAM as UTF-16LE text, in
one table -- the notes said for weeks they were artwork found nowhere in
memory, and that was simply wrong. But the table cannot be read at runtime: it
is loaded during play, not with the screen, and on a freshly booted emulator
sitting on the scenario list a scan of all 31 MB found the names **nowhere at
all**. Tested directly, after a restart.

So the table was walked once, offline, out of a capture that had it, and the
names shipped. Same result, no runtime dependency, nothing to go missing.

**Anchored at five points** -- scenarios 0, 1, 2, 3 and 21, each read off a
screenshot of the row it names. The anchor at 21 carries the rest: a single
insertion or omission anywhere between 3 and 21 would land Fateful Brothers
somewhere else, and it does not. `test_menus.py` checks every shipped name back
against the game's own table, so the two cannot drift apart by hand.

**What is worth a second look:**

- **Scenarios 22, 23 and 24** -- "Beautfiul Treachery.." (the game's own
  spelling), "Ultimate Science Battle" and "Destined Rivals" -- sit past the
  last anchor and rest on the table's order alone. That order has been exact
  for the twenty-two before them, so this is a small risk, but it is the one
  place a wrong name could still be spoken. Confirmed the moment the player
  unlocks any of them: if what they hear does not match the screen, these are
  why.
- **The table runs on into battle stage names** -- Wasteland, Namek, Kame House
  -- so it stops at 24 on purpose. A stage announced as a scenario would be the
  confident error this project exists to avoid.
- **Where the table is, and when it loads**, is recorded in
  `docs/memory-map.md` in case it is ever wanted live. Entering a scenario is
  the suspected trigger; it was never pinned down because it stopped mattering.

### 4. The event name is gone from F12, and reading it properly still needs an index

`0x00D1A782` was recorded as the Game Level event name. It is not a display
slot -- it is entry 0 of a table of event names on a `0x40` granule, and it
reads "Mysterious Alien Warrior" on every event and even on Select Scenario,
where no event name is shown. The captures it was derived from were all taken
on event 00, where a table base and a display slot are the same bytes.

**It is no longer announced**, as of 2026-09-07, when the player asked for F12
to be fixed. That loses nothing that was ever true, and the instruction line --
the part that was -- is still read.

Reading the real one needs **the current-event index**. The story event list is
the likeliest place for it and needs mapping anyway.

**The table is not regular, so `0x00D1A782 + 0x40 * n` is not the fix** -- that
was recorded here and is wrong. Walking it offline
(`python story_probe.py names`) gives 230 entries in 240 granules: six names
are longer than 31 characters and continue into the following granule, and one
granule is empty. From the first long name onwards, arithmetic indexing reads a
continuation fragment -- "n!", "pe Baby", "use" -- and would speak it with the
same confidence as the bug it was meant to fix. The table has to be walked;
`story_probe.names` is the reference implementation and needs no player.

### 5. Verifications still owed

All cheap, all need the player at the controls. Ask before running any of
them -- see Testing with the player.

- **Game Level, leave and return.** Press Triangle to go back, re-pick the
  event, check it still tracks. Every cursor here is held to being tested on a
  transition it was not derived from; this one has not been. If it goes silent
  afterwards that is the two mirrors disagreeing, which is the design working.
- ~~The Select Scenario labels, when a third scenario unlocks.~~ **Done, twice
  over.** A third and then a fourth unlocked on 2026-09-07, the game turned out
  to *insert* rather than append, and the cursor the labels were indexed by
  turned out never to have been an index. All of it is settled and the names
  now hang off the game's own scenario numbers. See item 1 and the two
  scenario entries under Recently finished.
- **The main menu, with the stale-marker fix in.** The precedence rule went in
  after the last session the player ran, so it has not been heard working.
  Reaching the main menu after having been inside Dragon Adventure is the case
  that used to fail; it should now name the screen and read its options.
- **The Dragon Library marker, in a second run.** It rests on a single visit,
  unlike the main menu's and Options'.
- **Player 2 on the character select, through the guide app.** Player 1
  has been heard in play; player 2's pointer was verified on seven cued
  presses but not through the app. Confirm player 1, move on the lower grid:
  the first move should say "Player 2: name" and later ones just the name.
- **The tournament entry screen on a second visit**: it has been heard in
  play, but its marker rests on one capture and one visit.
- **The title screen, after the new rule.** It is only ever reached on a
  fresh boot, and the rule that refuses its marker while text is on screen
  was measured on captures, not heard. Boot the game with the guide running:
  it should still say "Title" and "New Game".
- **The main menu after Dueling.** The character select's marker sits in the
  dynamic region, which is torn down between screens for every screen seen so
  far, but no capture has been taken by that route. Reaching the main menu
  after Dueling is the transition that would show a stale marker, exactly as
  it did for Select Scenario. If the main menu goes quiet there, that is
  where to look, and the log will name the collision.

### 6. Map the remaining screens

- **The character select in Ultimate Battle Z.** Dragon Tournament turned
  out to load the same sprite at a different address, so Ultimate Battle Z
  probably does too. One `check` on that screen says where, and one line
  adds it; the Dueling and Tournament entries are the pattern.
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
  marker found before a cursor is worth looking for. These are also the
  screens an OCR fallback would help most; see *Reading labels that are
  artwork*.

Follow **Adding a screen** in `docs/memory-map.md`; it is a checklist because
sessions have skipped its steps and shipped bugs each time. Two entries were
added to it on 2026-09-07 and both were paid for: check a marker against
captures taken by the *route* that reaches the screen, not just any captures;
and for a list that grows, look for the list itself and not only its cursor.

### 7. Teleport-driven calibration: works. Does it work on a second map?

`bt2/mapcal.py` on the **C** key. Six commanded hops -- a probe out, back, then
a closed square -- each one a known world displacement, so the Jacobian is
solved from movement the guide controls rather than movement the player cannot
produce. The last hop is the trip home, so finishing normally *is* the return;
nothing extra has to be trusted to put the player back.

It reuses `calibration.py`'s `solve_jacobian`, `Calibration` and its
`confident` test unmodified, so a scale learned this way is trusted on exactly
the same evidence as one learned by flying, cross-check included. What it owns
is the correspondence: `ArrowIdentifier` decides which white blob is the arrow
from drift while the player stands still, which needs the player moving under
their own power, so `mapcal` matches blobs across hops instead and takes the
one track a single plausible Jacobian explains. Two tracks that both fit is
reported as ambiguity, not resolved by picking.

**What the live run settled**, 2026-09-07, on Blue landmass at 1066x705:

    jacobian  [ 4.242e-05, -3e-08, 1.2e-07, -5.456e-05 ]
    6 movements spanning 90 degrees, cross-checked to 0.04%, and again to 0.06%

Three of the four things listed here as unproven are now proven. A paused frame
does still read as the Dragon Adventure HUD, so the run can see the pause it
asked for. The arrow is separable from the real map's clouds over six hops.
And the answer is independently credible: `anchor.py` argues from other evidence
that the minimap is axis-aligned, and the measured cross terms are -3e-08 and
1.2e-07, which is zero at this precision.

**What is still open is the only thing that matters now: a second map.**
Everything above is one map. Specifically unproven:

- **A map whose scale is not near the documented 0.00004.** The probe measures
  the scale, but the probe's own size is guessed from the coordinate table's
  extent, and a scale far off would put the arrow outside the match radius. The
  run refuses honestly in that case ("the minimap arrow was not visible for the
  whole run") rather than inventing an answer, so the failure is safe -- but it
  is a failure, and the fix would be to retry with a shorter probe rather than
  give up. **Not done, because no map is known to need it.**
- **A map with a different destination layout.** 89 of 117 sampled start
  positions calibrate on Blue landmass. A denser map could refuse more often.

**When the player reaches a new map, run C there and record what happens.**
That is the single next piece of evidence this feature needs.

**Two things the live run found that were nothing to do with the maths:**

- **`say(once=True)` was defeated by any two notices that alternate.** It
  compared against a single last-spoken slot, so two once-only lines each
  cleared the other's record and both repeated for ever -- eleven times in
  three seconds in the log. It now remembers the last eight lines.
- **The teleport handler threw away the arrow anchor after every world
  teleport**, so the guide asked a player who cannot move to "move briefly so
  the player arrow can be identified", immediately after moving them. With a
  confident calibration the anchor is now carried through the jump.

**The pause is still manual, six times per run.** That is the friction worth
removing next -- see the pause note under Also worth doing.

**`cycle_destination` has no offline test.** The story slot was verified in
play and by reading, not by a check that would catch a regression. There is no
`test_guide.py` and building the fakes for one is a real piece of work; worth
doing before that method is next changed.

### 8. Finish the story reader

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

**Features the pointer makes cheap:**

- ~~Dragon Library and Select Scenario prose.~~ **Done.** F12 reads whatever is
  on screen, mapped or not, so both are covered and needed no new addresses.
- **The 26 scenario synopses** are now the most promising piece of work here,
  because the thing that blocked them has gone. They are resident at
  `0x00D1E3C0`-`0x00D24D40` whenever Dragon Adventure is open, and the game
  renders them from a computed offset with no display copy, so speaking the
  highlighted one needed the current-scenario index -- **which `0x00B05308`
  now gives.** What is left is working out how a scenario number indexes the
  pool: 26 scenarios share 123 boxes, so it is not a fixed stride and the pool
  has to be walked, as the event-name table does. Every Dragon Adventure
  capture on disk has the pool resident, so **this can be done entirely
  offline**, with no player and no emulator.
  It is also the closest thing to naming a scenario automatically: a newly
  unlocked one whose name has never been seen could still be *described* in
  the game's own words.
- **Replacing the F12 subtitle machinery.** One pointer supersedes the ten
  recorded subtitle addresses and the shape-based relocation search, and does
  not move between runs where they do. See **Decisions waiting on the player**;
  this changes behaviour that already works, so it is not done unasked.

### Reading labels that are artwork

Raised by the player 2026-09-07: is OCR a better general plan than hunting an
address per screen? Nothing has been built or installed; this is the reasoning
so far, so the next session need not start it over.

**It would not have helped the scenario list.** The bottleneck there was never
reading the words -- a screenshot answers that in seconds -- but knowing
whether a row still *meant* what it used to. That is an identity question, and
memory answered it with `0x00B05308`.

**Where it would pay** is the screens that are still silent: Item Shop, Data
Center, Ultimate Battle Z, Evolution Z, the story event list. Those are silent
because their labels are artwork *and* nobody has mapped a cursor. OCR would
give the text and the selection together, and would generalise instead of
needing a derivation session per screen.

**Nothing is installed** -- no tesseract, no `winsdk`, no `cv2` -- checked
2026-09-07. Engines, in the order they suit this project:

- **`Windows.Media.Ocr`** is the right one. Built into Windows 10 and 11, so
  no download and no shipping weight, offline, and the desktop app is already
  C# where it is native. From Python it needs the `winsdk` package, about
  10 MB.
- **Tesseract** is 50-100 MB with language data, and a stylised outlined italic
  font over an animated background is its weak spot.
- **Neural OCR** (PaddleOCR, EasyOCR) pulls in torch: hundreds of megabytes
  against an 8.5 MB worker. Out of proportion.

**The risk is this project's own standard.** OCR produces a confidently wrong
reading far more readily than a memory address does, and a confident error is
the failure treated here as worse than silence. So it should be an *announced*
fallback -- "reading the screen: Lord Slug" -- never something the player
cannot tell apart from a memory read, and never allowed to override one.

**A cheaper cousin worth remembering.** The labels are pre-rendered artwork, so
each is the same bitmap every time. Hashing the highlighted row's pixels gives
*identity* without reading words at all -- the same thing `0x00B05308` gave for
scenarios, but generalised to any menu. Each name would still have to be seen
once, as it must whatever route is taken, because the words exist nowhere but
in the picture.

**Cheapest next step, and it needs no player:** one screenshot of an unmapped
menu through Windows OCR settles whether this font is legible to it at all. If
it is not, the question is closed for half an hour's work.

**One screen has since come off this list without OCR.** The character select
looked like another artwork menu and was not: its names are drawn as text, and
the game's own pointer to that text followed the highlight. **Check for that
first on every remaining silent screen** -- read `story.displayed` on two
captures at different positions -- because where it holds, the screen costs
one cued scan and no table at all.

### Also worth doing

- **The N and B latch is fixed, and it was a real one.** Choosing a destination
  used to be permanent until the map changed: `destination_chosen` is cleared
  only by `reset_surface`. So a player who calibrated, teleported to the story
  marker, then pressed N to hear what else was around could not get back to it.
  That is exactly what happened in play on 2026-09-07. The story marker is now
  the last entry in the cycle instead, so N and B reach it like anything else.

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

- The standalone `menu_announcer.py` **keeps its own `Screen` class and its own
  table**, which is worth knowing before editing it: it shares nothing with
  `bt2/menus.py` but the addresses, so a change there does not reach it and a
  reference to the shipped class will not even resolve. What it lacks, as of
  2026-09-07: the mirror cross-check, named-marker precedence, the rule that a
  marker outliving its screen loses, the second signature and relocation
  search, scenario numbers, and the story-reader fallback on F12. Its table
  still holds four screens -- neither Game Level nor Select Scenario -- so it
  is silent on both, and it still says "Unknown screen" on every transition.
  It is a development tool, so this matters only during a long probing session,
  but the gap is now wide enough that **`menu_probe.py dryrun` is the better
  way to hear what the mod would say**: it drives the real reader.
- Nothing checks read text against the extracted corpus at runtime, and that
  is now a settled decision rather than a gap. The corpus is a **search** tool
  rather than a runtime dependency -- the ten main menu subtitle lines score zero against it,
  so a runtime corpus match would reject real text and tie the mod to English.
  What `bt2/story.py` does instead is check the *alphabet*: ASCII, newline and
  General Punctuation, which is every character the 2,601 boxes use. That
  refuses garbage and move-list glyphs without knowing a single word.

## Recently finished

### 2026-09-08: the character select speaks, and needed no cursor

- **Player 1's highlighted character is announced** on the Dueling grid,
  read from the game's own text. `0x008C6244`, the pointer the story reader
  and F12 already use, aimed at the highlighted name in all eight captures --
  one taken before the cued scan, seven during it, across both axes -- each
  checked against its screenshot. No cursor address, no table of names,
  nothing transcribed. Confirmed live through `dryrun`.
- **The mod had been calling this screen the Title screen**, by the weak byte
  signature that fooled it on Game Level, and would have said "New Game" over
  the grid. A named marker for the screen now outranks it.
- **The names are in the game's own table** -- 135 UTF-16 entries at
  `0x00D61C00`, Goku through "Password Character" -- and some carry a badge
  glyph after the name that the story alphabet refused, which is the only
  reason F12 said nothing on Goku. A trailing badge is now dropped; the same
  glyph mid-line stays refused, because a battle once drew one.
- **Player 2 was silent in play, and the log said so in one line**: forty
  player 1 names, then nothing after the confirm. The pointer stayed on
  player 1's choice. A search of every capture for words pointing into the
  name table found exactly two: that pointer and a second draw structure
  0x98 bytes after it, aimed at player 2's name. It was found from captures
  in which player 2 had never moved, so a second cued scan of seven presses
  on player 2's grid was run before shipping it, and it matched every
  screenshot while player 1's stayed put. The reader now watches both.
- **A search for the highlighted index found no byte-sized ramp** across the
  seven captures, and it was not needed. Two weak candidates for the column
  and row are recorded in `docs/memory-map.md`, unverified and unshipped.
- **`positionscan` and `fit` take `--prefix`**, because their default file
  names are the Select Scenario archive that `test_menus.py` checks. Running
  the old tool on a new screen would have overwritten the evidence for an old
  one.
- **Dragon Tournament's entry screen was silent, then said "New Game".**
  Both from one log: the Dueling marker is at a different address in this
  mode, so the screen went unnamed, and the title signature flickered on
  over it. It has its own entry now, reading one name pointer -- the second
  draw slot holds stray menu text there and would have been announced as a
  player 2. And the title signature is refused while the game draws text,
  which every misnamed screen did and the title capture does not.
- 349 checks in `test_menus.py` over 44 captures, 46 in `test_story.py`.

### 2026-09-07, in one paragraph

Five entries follow, **newest first**, from a single long session that started
with the player saying menus had stopped reading their options. The arc is
worth having in order, because each step made the next one findable. A stale
Dragon Adventure marker was taking the main menu's name away, and the story
reader was filling the silence with option subtitles. Fixing that exposed the
scenario list, whose cursor had never been an index -- a two-entry list cannot
tell a cursor from a coin toss. Fixing *that* left names keyed by list length,
which cost the player every name the next time a scenario unlocked. And that
finally prompted the right question -- where is the *list*, not the cursor --
which found `0x00B05308`. Asking the same kind of question once more -- where
are the *names* -- found them too, in a table the notes had long insisted did
not exist, and that is what makes the guide handable to someone else. **Later
entries supersede earlier ones**; the superseded claims are marked where they
appear.

Three lessons outlast the addresses. A marker's exclusivity is only as good as
the routes the captures took to reach the screen. A search that asks for
something that changes with the cursor cannot find something that does not. And
a negative recorded in these notes is worth re-testing before it is built on --
"the names are nowhere in RAM" was written down as settled and was false.

### 2026-09-07: every scenario named, from the game's own table

- **All twenty-five scenario names ship with the guide**, walked out of a table
  the game keeps in RAM. **This is what makes the guide handable to someone
  else**: a player who unlocks a scenario hears its name, with no tools, no
  editing and nobody who has Claude.
- **The notes were wrong for weeks.** They said the names were artwork "found
  nowhere in RAM and nowhere in the disc corpus, searched end to end". They are
  in RAM, in the same shape as the event-name table -- which should have been
  the hint, since that table had already been found and had already taught the
  lesson that such a table must be walked rather than indexed.
- **Reading it live was tested and does not work.** PCSX2 was restarted, the
  save reloaded to the scenario list, and the names were not at the address --
  nor anywhere else in 31 MB. The table loads during play, not with the screen.
  So it was read once, offline, and the answer shipped.
- **Anchored at five screenshots**, with the anchor at 21 carrying everything
  between. The tests walk the table out of a capture and check every shipped
  name against it.
- **Stopped at 24 on purpose**: the table continues into battle stage names.
- 223 checks in `test_menus.py`, over 27 captures.

### 2026-09-07: the game's own list, and the end of re-deriving names

- **`0x00B05308` is an array of which scenarios the list is showing**, one per
  row in row order: `[0, 21]` at two entries, `[0, 1, 21]` at three,
  `[0, 1, 2, 21]` at four, `[0, 1, 2, 3, 21]` at five. Names are keyed by those
  numbers instead of by row, so **an unlock now costs one unnamed row rather
  than all of them.** Checked against all thirteen captures that have a
  screenshot beside them, over four list lengths and several sessions, then
  read back live.
- **Then a real unlock tested it.** Final Battle arrived as number 3, landed
  between Lord Slug and Fateful Brothers exactly where numerical order says,
  and cost one row. Adding it was one line. The previous design would have cost
  all five names.
- **It also explains the insertions.** The list is the unlocked scenarios in
  numerical order, and Fateful Brothers is 21, so it keeps being pushed to the
  end. What looked like an arbitrary rule is a sort.
- **Lord Slug unlocked at index 2** and cost every name for an hour, which is
  what prompted looking properly.
- **Three earlier searches said no identity existed, and that was wrong.** They
  all asked for something that changes as the cursor moves; the array does not,
  because it is the list rather than the selection, so none of them could have
  found it. Asking about *shape* instead -- the shorter list is a subsequence
  of the longer -- found it at once. Recorded in `docs/memory-map.md`, mistake
  included, because the mistake is the reusable part.
- **`rowscan --capture`** keeps the RAM as well as the picture, and throws away
  any capture the player moved during rather than pairing a picture of one row
  with a capture of another.
- 223 checks in `test_menus.py`, over 27 captures.

### 2026-09-07: the scenario list, and a cursor that was never one

- **Select Scenario speaks all three rows**, confirmed live against a
  screenshot of each. `0x00D53625` had been its cursor since the screen was
  mapped and is not an index at all -- it reads 1 for two different rows. The
  cross-check `0x00B0536C` is the real thing, and also explains the rows drawn
  above and below the highlighted one in every screenshot.
- **A list of two entries cannot derive a cursor.** Position and parity are the
  same thing there, so six cued presses, three captures and a held-out seventh
  all fitted an address that was never right. The original notes said to
  re-check when a third scenario unlocked; the screen going silent in play is
  what that re-check cost by being deferred.
- **The game inserts, it does not append.** Tree of Might landed at index 1 and
  moved Fateful Brothers from 1 to 2, so extending the table would have renamed
  both scenarios that were already there. Names were keyed by list length as a
  result -- **superseded hours later** by the scenario numbers above, after that
  design cost the player every name at the next unlock.
- **`menu_probe.py rowscan` is new**: it reads a few known addresses at 10 Hz
  and photographs the screen the moment they settle on a new value, so every
  row the player passes through is recorded beside a picture of it. Seconds and
  kilobytes, where `positionscan` costs minutes and 31 MB per press.
- **The cross-check is gone with the impostor**, and that is a real loss.
  Searched for afterwards over all twelve scenario captures: **there is no
  second copy in EE RAM.** See item 2 under Next steps.

### 2026-09-07: the leftover marker, and menus made quiet

- **The main menu's silence was a stale marker, and the log said so** the first
  session after the diagnostic went in: `mc_da_2_text_off_l` still resident
  after Dragon Adventure had been left, colliding with the real marker 168
  frames in a row. It had also been announcing "Select Scenario" over the
  Options screen. A marker known to outlive its screen now loses to one that is
  not, recorded per screen from what has actually been seen.
- **Every capture on disk was clean, and that was the trap.** The
  non-Adventure captures were all taken in sessions that had never entered
  Dragon Adventure. A marker's exclusivity is only as good as the routes the
  captures took to reach the screens.
- **The story reader speaks only out of the scene text buffer**, at the
  player's request: no speech on a menu the mod has not been taught. Cutscene
  text is loaded into a buffer around `0x0109F000`; menu prose lives in the
  menu's own allocation, three and a half megabytes below the nearest scene box
  in every capture. F12 is outside the rule and still reads either.
- **A silent row now explains itself.** Two cursor copies that will not agree
  used to mean permanent silence, indistinguishable from a broken mod. The mod
  says so once and logs each distinct pair of values. **It worked**: that is
  what identified Select Scenario's real cursor within the hour. The mechanism
  stays for the next screen, though Select Scenario itself no longer has two
  copies to compare.
- **Diagnostics no longer repeat.** The first collision note wrote the same
  line 168 times in one session.
- 126 checks in `test_menus.py`, 44 in `test_story.py`, all offline.

### 2026-09-07: menus speak again, and F12 answers everywhere

- **The menu option now wins over the story reader, explicitly.** One method,
  `MenuReader.reads_options()`, decides which of the two speaks, and it is true
  only when the mod has named the screen, that screen has a mapped cursor, and
  the evidence that named it also locates that cursor. The old gate was
  "the menu reader does not know this screen", which said nothing about the
  third condition.
- **The main menu is recognised twice over.** Five sprite names in a
  longer-lived block name the screen when the marker beside its cursor has
  gone; a bounded search then finds where that block went, and only then is the
  cursor read. A screen that names itself but cannot locate its cursor stays
  honest: it says where you are and leaves the options to the prose reader.
- **Its cursor is now cross-checked**, against the second copy at `0x00CF9C34`
  that was documented and never wired, as Options' and Game Level's already
  were.
- **F12 was dead on every screen the mod could not name**, because it was read
  below an early return. It is read on every pass now, and falls back to the
  display pointer, so it answers on unmapped menus and cutscenes too -- and
  says "Nothing written on screen was found." rather than nothing at all.
- **The wrong event name is gone from F12.** It announced the first event's
  name on every event.
- **Detection now writes its own diagnosis to the log.** An ambiguous match
  names the colliding screens; a relocated block reports how far it moved.
  Neither is spoken. Two screen faults have now been reasoned about wrongly
  before being measured, and the log is the cheapest place to stop that.
- **`test_menus.py` is new**: offline checks over all 21 captures, with no
  emulator and no player. Every screen's markers must match its own captures
  and no other, in both directions; F12 must read the line the screenshot
  shows; and a synthetically moved block must be found again.
- **A latent rate-limit bug went with it.** Both searches compared against a
  last-run time of 0.0, so on any clock starting near zero the first search was
  refused -- which is every clock in a test.

### 2026-09-07: the map teaches its own scale

- **C calibrates a map by teleporting**, and it worked the first time it was
  run properly: two runs on Blue landmass, cross-checked to 0.04% and 0.06%,
  after which T reached the story objective. `bt2/mapcal.py`, 30 offline checks
  in `test_mapcal.py`.
- **The story marker joined the N and B cycle**, which is what the player
  expected it to do and what makes the calibration usable rather than merely
  correct.
- **Two long-standing annoyances went with it**: repeated once-only notices,
  and being asked to move right after a teleport.
- **The first attempt refused, correctly by its own rule and wrongly in fact.**
  It would not start because the player was standing on a destination -- which
  is where teleporting always leaves them. Recorded under *What the first live
  run measured* in `docs/memory-map.md`.

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
- **`rowscan` is the cheap way to ask the player for evidence.** It needs no cue
  schedule to follow: they press Down and pause, and every state they pass
  through is recorded with a picture. A minute, and it settled two questions on
  2026-09-07 that had each looked like a probing session. Prefer it to
  `positionscan` unless a *new* address has to be searched for.

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
