# Project status

Screen reader support for Dragon Ball Z: Budokai Tenkaichi 2, played in PCSX2.
Read this first when resuming. Details of every address live in
`docs/memory-map.md`.

Last updated: 2026-09-06.

## What works today

Menus speak through NVDA, driven by the game's own memory:

- **Title screen** -- New Game / Load Game.
- **Main Menu** -- all ten options, Dragon Adventure through Dragon Library.
- **Options** -- all five entries, Save and Load through Exit. The game keeps
  two copies of this cursor and both are read; if they ever disagree the mod
  stays silent rather than guess.
- **Game Level** -- the difficulty chooser inside Dragon Adventure, reached
  after picking a story event. Levels 1, 2 and 3, chosen with Left and Right.
  F12 reads the event name and the instruction line, both the game's own text.
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

Menu reading is **part of the guide app**. `bt2/menus.py` runs inside the guide
worker's main loop, at the one point where navigation guidance is suspended --
outside Dragon Adventure, which is exactly when the player is in a menu. The two
therefore never talk over one another. Press **F12** for the highlighted
option's spoken line. If the text block has moved since these notes were
written, the mod says "Looking for the subtitles.", finds it again, and carries
on.

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
guide, exactly as before. Menus now speak. Requirements are unchanged:

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

## Next steps, roughly in order

**When a screen is silent or names itself wrongly, run `python menu_probe.py
check` before theorising.** Both faults found on Game Level were invisible from
outside the mod and obvious in one line of that output, and both were reasoned
about wrongly first.

### 1. Verifications still owed

All cheap, all need the player at the controls. Ask before running any of
them -- see Testing with the player.

- **Game Level, leave and return.** Press Triangle to go back, re-pick the
  event, check it still tracks. Every cursor here is held to being tested on a
  transition it was not derived from; this one has not been. If it goes silent
  afterwards that is the two mirrors disagreeing, which is the design working.
- **The event name on a second story event.** `0x00D1A782` has been seen for
  event 00 only. **No longer blocked**: the player has since cleared several
  events, so this can be checked whenever they are next on a Game Level screen.
  It stays on F12 until then, which is why it is on F12.
- **The Dragon Library marker, in a second run.** It rests on a single visit,
  unlike the main menu's and Options'.

### 2. Map the remaining screens

- **The story event list**, inside Dragon Adventure -- the screen Game Level is
  reached *through*, where the player is choosing blind. Almost certainly needs
  `in_adventure=True` like Game Level, since the HUD heuristic will call it
  gameplay too. Probably the highest value of the three.
- **Dragon Library** -- detected, but cursor and labels both unknown.
- **Ultimate Battle Z and the rest** -- not detected at all, so each needs a
  marker found before a cursor is worth looking for.

Follow **Adding a screen** in `docs/memory-map.md`; it is a checklist because
this session skipped two of its steps and shipped two bugs.

### 3. Teach the map scale by teleporting, not flying

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

### 4. Dragon Adventure story subtitles

The largest untouched win, and the groundwork is now in place: `extract_text.py`
gives 2,458 distinct lines, which is the filter that makes the search
tractable. The one open question is unchanged -- how to tell which line is
*currently* displayed, since a cutscene has no cursor. Needs one capture session
inside a cutscene; the method is in the TODO in `docs/memory-map.md`.

Cutscenes continue to appear as the story advances, so a capture session can be
taken at the next one rather than needing a fresh save.

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
  PCSX2 by hand and press T again. Worth checking whether the guide can pause
  and resume the emulator itself around the write, which would make teleport a
  single keystroke.
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
  precedence. The shipped `bt2/menus.py` has all three. It is a development
  tool, so this matters only during a long probing session -- but it means it no
  longer reflects how the mod behaves.
- Nothing checks read text against the extracted corpus yet. Deliberate:
  nothing reads story text yet either, and building the check first would be
  building against nothing.

## Recently finished

- **The story corpus can be extracted offline.** `source/tools/extract_text.py`
  reads the disc directly: 2,458 distinct lines of cutscene dialogue, narration
  and tutorials, agreeing with the 2,601 counted independently before. This is
  the filter the cutscene work depends on. Until now the docs pointed at
  parsing that had never been committed.
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
  proved nothing.
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
