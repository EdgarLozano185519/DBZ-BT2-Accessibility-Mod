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

Run it with the project virtual environment, from `source/tools`:

    ..\..\.venv\Scripts\python.exe menu_announcer.py --seconds=120

This is a prototype in `source/tools`, not yet part of the shipped guide. It has
not been wired into `guide_host.py`, the WinForms UI, or the packaged worker.

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

1. **Fix two known announcement flaws** (both in `docs/memory-map.md` under
   Known gaps): "Unknown screen" is spoken on every screen *transition* rather
   than only on genuinely unmapped screens, and the first option can be
   announced spuriously on re-entering a screen because the cursor briefly
   reads 0. Both need a settling delay.
2. **Map more screens.** Options' labels are known but its cursor address is
   not. Dragon Library is detected only. Ultimate Battle Z and the rest are not
   detected at all. Use `menu_probe.py pressscan`, then `labels`.
3. **Dragon Adventure story subtitles.** The largest untouched win. Story text
   is real UTF-16LE in `TXT-US-*` inside `ZS2US_1.AFS`, on-screen prose is
   demonstrably readable from RAM, and the menu subtitles prove the subtitle
   system works. The one open question is how to tell which line is currently
   displayed, since a cutscene has no cursor. Needs one capture session inside a
   cutscene -- see the TODO in `docs/memory-map.md` for the method.
4. **Integrate.** Fold the announcer into the guide proper so it runs alongside
   the existing Dragon Adventure navigation rather than as a separate script.

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
