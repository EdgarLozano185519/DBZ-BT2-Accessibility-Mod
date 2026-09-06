# Project status

Screen reader support for Dragon Ball Z: Budokai Tenkaichi 2, played in PCSX2.
Read this first when resuming. Details of every address live in
`docs/memory-map.md`.

Last updated: 2026-09-06.

## What works today

Menus speak through NVDA, driven by the game's own memory:

- **Title screen** -- New Game / Load Game.
- **Main Menu** -- all ten options, Dragon Adventure through Dragon Library.
- **Screen detection** -- the announcer works out which screen is showing and
  picks the matching labels, or stays silent when it cannot.
- **Menu subtitles on F12** -- the character's spoken line for the highlighted
  main menu option, read as the game's own text rather than from a table we
  wrote. On a key press only, so it does not slow down browsing.

Menu reading is **part of the guide app**. `bt2/menus.py` runs inside the guide
worker's main loop, at the one point where navigation guidance is suspended --
outside Dragon Adventure, which is exactly when the player is in a menu. The two
therefore never talk over one another. Press **F12** for the highlighted
option's spoken line.

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

1. **Map more screens.** This is the next real work. Options' labels are known
   but its cursor address is not. Dragon Library is detected only. Ultimate
   Battle Z and the rest are not detected at all, so the announcer names them
   "Unknown screen" -- correct, but not useful. Use `menu_probe.py pressscan`
   to find each cursor, then `labels` to write the table from what was actually
   on screen.
2. **Re-verify the Options and Dragon Library markers.** Both rest on a single
   visit each, unlike the main menu's, which held across nineteen captures. A
   marker that shifts between visits would make the announcer name the wrong
   screen. Cheap to check: visit each twice in separate PCSX2 runs.
3. **Dragon Adventure story subtitles.** The largest untouched win. Story text
   is real UTF-16LE in `TXT-US-*` inside `ZS2US_1.AFS`, on-screen prose is
   demonstrably readable from RAM, and the menu subtitles prove the subtitle
   system works. The one open question is how to tell which line is currently
   displayed, since a cutscene has no cursor. Needs one capture session inside a
   cutscene -- see the TODO in `docs/memory-map.md` for the method.
4. **Find the subtitle block by content instead of by address.** The ten menu
   subtitle addresses come from a single PCSX2 run and may move between runs.
   Today every read is checked for plausible text and refused if it is not, so
   the failure is a spoken "no subtitle available" rather than gibberish --
   safe, but it means F12 can simply stop working after an emulator restart.
   Searching for a known line at startup would fix that for good, and the same
   search is what the cutscene work needs anyway.

Smaller, optional:

- The standalone `menu_announcer.py` still says "Unknown screen" on every screen
  transition. The shipped `bt2/menus.py` no longer does. The standalone is a
  development tool, so this only matters if it is used for a long probing
  session, where the interruptions are tiring.

## Recently finished

- **The two announcement flaws are fixed** in the shipped path. "Unknown
  screen" now waits 1.5 seconds before speaking, so the gap between one screen
  unloading and the next loading passes silently. The cursor must read the same
  value twice before it is trusted, so the spurious first option on re-entering
  a screen is gone.
- **The announcer is integrated.** `bt2/menus.py` runs inside the guide
  worker's loop rather than as a separate script, and the worker in `worker/`
  is built from it.

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
