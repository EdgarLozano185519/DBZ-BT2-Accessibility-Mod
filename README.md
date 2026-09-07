# DBZ BT2 Accessibility Guide

Screen reader support for **Dragon Ball Z: Budokai Tenkaichi 2** (PlayStation 2,
USA release), played in the PCSX2 emulator. It speaks menus aloud and gives
spoken navigation guidance in Dragon Adventure, so the game can be played
without sight.

It reads the game's memory while it runs. It does not modify the game, the disc,
or your saves.

This package contains **no game, BIOS, emulator, save data or disc image**. You
supply your own.

---

# For players

## What you need

- **Windows 10 or 11, 64-bit**, with .NET Framework 4.8 (already present on most
  systems)
- **PCSX2**, your own installation. Tested with 2.9.32; the original release
  targeted 2.6.3
- **A PS2 BIOS dump** and your own copy of the game: **SLUS-21441**, CRC
  **FE961D28** (USA release). Other regions are not supported
- **NVDA**, if you use it. Windows' built-in SAPI voice is the automatic
  fallback, so the guide still speaks without it

You do **not** need Python, pip, a terminal, or any runtime install. Everything
the guide needs is inside it.

## Running it

1. Extract the whole folder, keeping `worker` beside `DBZ BT2 Guide.exe`. Do not
   run it from inside a ZIP.
2. Set up PCSX2 normally first: BIOS, controller, memory card.
3. Open **DBZ BT2 Guide.exe**. On first run it searches for your PCSX2 and game;
   pick one if several are found, then Save.
4. Choose **Open game**. With PCSX2 closed, this switches on the connection the
   guide needs (PINE) in that installation's own settings, saving a backup of
   your `PCSX2.ini` first.
5. Choose **Start guide**.

You can also launch the game yourself in PCSX2 and then press Start guide; the
Settings paths only matter for the Open game button.

Guidance pauses whenever another window has focus, so you can use your screen
reader normally without the guide talking over it.

## What it does today

**Menus speak.** Moving the cursor announces the highlighted option on:

- the **title screen** — New Game, Load Game
- the **main menu** — all ten options
- **Options** — Save and Load, Controller, Screen, Sound, Exit
- **Game Level**, the difficulty chooser reached after picking a story event in
  Dragon Adventure — Level 1, 2 or 3, chosen with Left and Right

Screens it recognises but has not mapped are named and then stay quiet; screens
it does not recognise say so, rather than guessing. Where the game keeps two
copies of the cursor, both are read, and if they ever disagree it stays silent
rather than name the wrong option.

**F12 speaks the game's own text.** On the main menu, the character's spoken
line for the highlighted option. On Game Level, the name of the story event and
the instruction line. It is on a key press so that browsing stays quick. If the
text has moved since it was last recorded, F12 says "Looking for the subtitles",
finds it again, and carries on.

**Dragon Adventure navigation.** The original guidance: it picks an objective
from the live minimap, tracks your position, and uses stereo direction and pitch
plus spoken messages to steer you there.

**G says how far, and which way to turn.** The tones are in world directions —
stereo left and right mean west and east — which only helps if you can see
which way you are pointing. G reads your actual heading out of the game and
answers in your own terms: "map point 4, hard right, 1691 units."

It answers every time it is pressed, whether or not the story objective has
been worked out. If your position cannot be read it says so; if it can read
your position but not your heading it gives the compass bearing and says that
is what it is, rather than dressing a compass point up as a turn.

**N and B choose the destination.** They step through what the map is offering.
G then reports whichever you picked, and **T teleports you there** — so a place
can be reached without flying to it. The guidance tones keep following the
story objective, so choosing a destination changes where T goes without
changing what the tones are steering you toward.

Teleporting still requires pausing PCSX2 by hand first: writes race the
emulator's CPU thread otherwise. The guide says so if you press T without
pausing, every write is read back to confirm it, and a failed write is rolled
back.

With the game focused:

- **F12** — the game's own text for the current screen
- **G** — how far the destination is and which way to turn for it
- **N** / **B** — step through the destinations on the map. G then reports the
  one you picked, and T teleports there
- **T** — teleport to that destination (PCSX2 must be paused first)
- **R** — repeat the current destination
- **L1** on a detected DualSense — same as T
- **S**, **F**, **U** — record what a place turned out to be

## What it cannot do yet

Being honest about the limits, because silence from a screen reader is
indistinguishable from "working, nothing to say":

- **The story event list does not speak.** Choosing which story event to play
  is still done blind, even though the difficulty screen after it now speaks
- Dragon Library is named but its entries are not read. Ultimate Battle Z, the
  item shop, character select and battle menus are not recognised at all
- **Story cutscene subtitles are not read.** This is the largest missing piece
  and the next thing being worked on
- **Battles are not accessible** beyond the game's own audio
- The **event name** F12 reads on Game Level has only ever been checked against
  one story event, because only one is unlocked on the current save. If it ever
  reads a name that does not match the event you picked, that is why — please
  report it
- If text addresses no longer match, F12 says "no subtitle available" rather
  than reading nonsense
- Navigation is a playtest of Dragon Adventure, not whole-game accessibility.
  Unfamiliar maps still need wider testing

## If something goes wrong

- **Waiting for a connection** — close PCSX2 normally, confirm the right copy is
  chosen in Settings, then choose Open game so the guide can switch PINE on
- **Silent** — return focus to the game, check *Speak guide messages*, and read
  the Message history
- **The runtime is missing** — extract the whole package again, with its `worker`
  folder
- An unrecoverable startup error is written to `logs\last-worker-error.txt`

Settings, logs and learned maps live in `%LOCALAPPDATA%\DBZ BT2 Guide`.

When reporting a problem, include the release version, your PCSX2 version, what
you did and what you expected, and the relevant log. Review logs before sharing;
they can contain your map names and local paths. **Do not send game dumps, BIOS
files or saves.**

---

# For developers

## How it fits together

- **`DBZ BT2 Guide.exe`** — a C# WinForms interface (`source/tools/ui/
  GuideDesktop.cs`). Standard Windows controls, so screen readers handle it.
- **`worker/guide-worker.exe`** — a PyInstaller bundle of
  `source/tools/guide_host.py`. The UI starts it and reads its output.
- **`source/tools/bt2/`** — the guide itself. `guide.py` holds the main loop,
  `menus.py` reads menus, `vision.py` reads the HUD from captured frames,
  `memory.py` and `scan.py` find structures in PS2 RAM, `speech.py` and
  `speech_output.py` talk to NVDA with a SAPI fallback.
- **`source/tools/pine_client.py`** — PCSX2's PINE IPC protocol: arbitrary reads
  and writes of emulated PS2 memory over a local socket.

Menu reading runs at the one point in `guide.py` where navigation guidance is
suspended -- outside Dragon Adventure, which is exactly when the player is in a
menu. The two can therefore never talk over one another.

## The thing to understand first

**BT2's menu labels are pre-rendered artwork, not text.** Nothing in memory
spells "Dragon Adventure". The game stores the *index* of the highlighted
option, so the words come from tables in `bt2/menus.py` -- the only place that
text exists, and the only thing that can be translated.

**Prose is the opposite.** On-screen subtitles are held as verbatim UTF-16LE, so
those are read from the game rather than authored.

Getting this backwards wastes a lot of time. `docs/memory-map.md` records the
evidence for both, every verified address, and -- just as importantly -- the
dead ends, including several addresses that looked perfect and were not.

## Setting up

Requires Python 3.12 (x64) and Windows. If you do not have it:

    winget install -e --id Python.Python.3.12 --scope user

Note that a user-scope install does **not** provide the `py` launcher, so call
the interpreter by path. It lands in
`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. From the repository root:

    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv
    .venv\Scripts\python.exe -m pip install numpy==1.26.4 scipy==1.14.0 Pillow==10.4.0 pywin32==306 hidapi==0.15.0 pyinstaller==6.19.0

The pinned versions match `BUILD-INFO.json`. The menu reader alone needs only
pywin32; numpy, scipy and Pillow belong to the navigation and probe tooling.

`source/tools/vendor/nvda/x64/nvdaControllerClient.dll` must be present; the
source tree cannot speak without it.

Check the whole chain against a running game:

    cd source/tools
    ..\..\.venv\Scripts\python.exe pine_check.py

## Building

The worker is a compiled bundle, so **editing `bt2/*.py` changes nothing in the
app until you rebuild**:

    powershell -File source/tools/build_worker.ps1
    # then copy dist/guide-worker over the worker folder

    powershell -File source/tools/build_desktop.ps1
    # rebuilds the C# interface

    powershell -File source/tools/build_announcer.ps1
    # a small standalone menu reader, 26 MB, for testing menus alone

Both worker builds verify the result is x64 and refuse otherwise: the bundled
NVDA client is 64-bit, and a mismatch fails at runtime rather than at build
time.

## Finding new addresses

`source/tools/menu_probe.py` is the tool for mapping a new screen:

- **`pressscan`** — the workhorse. Speaks a varying number of button presses per
  sample and captures RAM after each, so the cursor follows a sequence no
  animation counter reproduces. It does not assume how many options a menu has.
- **`autoscan`** — captures RAM and the screen together and groups samples by
  the label's pixels. Exact on static screens, useless on animated ones.
- **`labels ADDR`** — walks a menu and saves a picture of each option, so the
  spoken table can be written from what was actually on screen.
- **`watch ADDR...`** — poll addresses live to see which hold steady.
- **`recorrelate`** — re-analyse the last capture from disk.

Captures land in `reference/`, which is git-ignored. **Never commit game
memory, extracted text or disc images.**

## Working principles

These were learned the hard way and are worth keeping:

- **Verify on a transition you did not derive from.** An address that fits the
  data it was found in has proved nothing. Several candidates looked perfect
  across every snapshot and then failed the first fresh transition.
- **Capture RAM and the screen together.** Pairing them is what makes a result
  trustworthy; snapshot-only searches produce confident wrong answers.
- **Speak instructions to the tester, do not print them.** They cannot read a
  terminal while playing, and leaving the game loses the menu to its attract
  demo. `probe_voice.py` does this. Allow about 30 seconds for them to reach the
  game after reading a message.
- **Never announce a guess.** For a player who cannot see the screen, a
  confidently wrong option is worse than silence. Every read is checked, and the
  mod says when it cannot help.
- **Prefer readable evidence to magic numbers.** Screens are identified by
  sprite-name strings the game loads, which can be checked, rather than by a
  state integer that can only be trusted.

## Where to start

`project_status.md` has the current state and the ordered next steps. The
largest one is **Dragon Adventure story subtitles**: the text is real UTF-16LE
in the disc's `TXT-US-*` files, on-screen prose is demonstrably readable from
RAM, and the menu subtitles prove the mechanism. The open question is only how
to tell which line is currently displayed, since a cutscene has no cursor.
`docs/memory-map.md` describes the method for settling it.

## Licensing

Third-party components and their licences are listed in `THIRD-PARTY.txt` and
the `licenses` folder.
