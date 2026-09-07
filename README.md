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
- **Select Scenario**, the Dragon Adventure scenario list — Saiyan Saga and
  Fateful Brothers, chosen with Up and Down
- **Game Level**, the difficulty chooser reached after picking a story event in
  Dragon Adventure — Level 1, 2 or 3, chosen with Left and Right

The scenario names are pictures rather than words in the game's memory, so the
guide reads them from a list written by hand. That list is right for the
scenarios unlocked when it was written. If you unlock another, the guide will
not know its name, and rather than say nothing it says **"Scenario 3, name not
known."** Please report it when you hear that: it means the list needs
rebuilding, and the names it already knows may have shifted.

Screens it recognises but has not mapped are named and then stay quiet; screens
it does not recognise say so, rather than guessing. Where the game keeps two
copies of the cursor, both are read, and if they ever disagree it stays silent
rather than name the wrong option.

**F12 speaks the game's own text.** On the main menu, the character's spoken
line for the highlighted option. On Game Level, the instruction line — and an
event name that is **currently wrong**, see below. It is on a key press so that
browsing stays quick. If the text has moved since it was last recorded, F12
says "Looking for the subtitles", finds it again, and carries on.

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

**Reaching a story event.** The red story marker on the minimap is a picture,
not a place the guide can look up, so it cannot teleport you straight to it.
What works, and what the mod is built around, is this:

1. **N** or **B** until you hear the destination you want to try.
2. **G** if you want to know how far it is and which way it lies.
3. **Pause PCSX2**, press **T**, then unpause. You are now standing on it.
4. Try the action button. If nothing happens, go back to step 1 and try the
   next one.

It is trial and error, and there are usually fewer than ten places to try. It
needs no flying, which is the point: it exists because moving accurately
without seeing the screen is the part that does not work.

**It tells you when the map changes under it.** If the destinations are
rearranged — finishing a story event does this — it says "Destinations
changed" and describes the new set. If it has to use a map's destinations
without being able to confirm they belong to the map you are on, it says so
once rather than presenting a guess as a fact.

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

- **The story marker cannot be teleported to directly.** It exists only as a
  marker drawn on the minimap, and turning that into a place needs a map scale
  the guide learns by watching you fly. Hence the trial-and-error loop above.
  Teaching it that scale by teleporting instead is the next planned change
- **The story event list does not speak.** The scenario list before it now
  does, and the difficulty screen after it does, but choosing the individual
  event between them is still done blind
- Dragon Library is named but its entries are not read. Ultimate Battle Z, the
  item shop, character select and battle menus are not recognised at all
- **Story cutscene subtitles are not read.** This is the largest missing piece
  and the next thing being worked on
- **Battles are not accessible** beyond the game's own audio
- The **event name** F12 reads on Game Level is **wrong on every event but the
  first**, and known to be. It is reading the first entry of the game's list of
  event names rather than the one you picked, so it says "Mysterious Alien
  Warrior" whatever you are playing. Ignore it for now; the instruction line
  beside it is correct. Fixing it needs the story event list mapped first
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

After rebuilding, stamp the release so the folder stays internally consistent:

    python source/tools/build_release.py --release=YYYY.MM.DD-rN
    python source/tools/build_release.py --check    # verify, change nothing

**It refuses to stamp a release whose worker is older than its sources**, which
is the mistake that costs a confused debugging session: the app looks fine and
behaves like the old code. `--check` is the quick way to ask whether the folder
is coherent.

## Finding new addresses

`source/tools/menu_probe.py` is the tool for mapping a new screen:

- **`check`** — **run this first when anything misbehaves.** Prints which
  screen markers match and in what order, what the guide settled on, what the
  cursor and its mirror read, and whether the HUD heuristic disagrees. Two
  faults that were invisible from outside the mod were each obvious in one line
  of it, and both were reasoned about wrongly first.
- **`keys`** — when a hotkey seems unreliable. Separates the three causes that
  all present the same way: the press never reaches the process, the game does
  not have focus so it is refused on purpose, or the loop looks too rarely to
  see it. It focuses the game itself before measuring.
- **`positionscan`** / **`fit`** — for menus the press scan cannot drive:
  horizontal ones, ones with few entries, ones reached only from inside a story
  event. `positionscan` captures after each *named* key press; `fit` finds the
  addresses that behave like an index. Read the positions back off the paired
  screenshots rather than assuming the presses landed — one missed press
  poisons the correlation while the run still looks clean.
- **`dryrun`** — runs the real guide loop with a recording speaker and prints
  every line it would say. The mod's whole output is speech, which otherwise
  cannot be checked without the player sitting at the controls.
- **`pressscan`** — the workhorse. Speaks a varying number of button presses per
  sample and captures RAM after each, so the cursor follows a sequence no
  animation counter reproduces. It does not assume how many options a menu has.
- **`autoscan`** — captures RAM and the screen together and groups samples by
  the label's pixels. Exact on static screens, useless on animated ones.
- **`labels ADDR`** — walks a menu and saves a picture of each option, so the
  spoken table can be written from what was actually on screen.
- **`watch ADDR...`** — poll addresses live to see which hold steady.
- **`recorrelate`** — re-analyse the last capture from disk.

`source/tools/extract_text.py` pulls the disc's story text offline — 553
`TXT-US-*` files, 2,458 distinct lines — with no emulator and no player
involved. It is the filter the cutscene-subtitle work depends on.

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
- **Measure before theorising.** Reasoning from the code about why a key
  "worked sometimes" produced two confident wrong answers in a row. Measuring
  it took minutes and gave the real one: the loop polls about four times a
  second, a key tap lasts a tenth of a second, and Windows shares the
  "recently pressed" bit with any other process that asks — so keys are now
  sampled on their own thread.
- **Store what the player decided; never re-derive it.** A chosen destination
  used to be looked up again each frame from a list rebuilt from the minimap,
  so a marker missing for one frame silently moved the selection and the
  teleport went elsewhere. Re-deriving turns a momentary gap in perception
  into a silent change of intent.
- **Read input before the loop gives up.** The loop abandons a pass when no
  objective has resolved. Anything read after that point is discarded in
  exactly the situations the player most needs it, and anything read into a
  local is lost when that pass returns.
- **Focus the game before testing keys.** The guide refuses hotkeys without
  game focus by design, so an unfocused test measures nothing while looking
  like a result. `bt2.windows.focus_game_window()` takes focus and verifies it.
- **Ask the player before running anything, and say whether they are needed.**
  Their time at the controls is the scarce resource; read-only checks and
  synthesised presses are not.
- **Prefer readable evidence to magic numbers.** Screens are identified by
  sprite-name strings the game loads, which can be checked, rather than by a
  state integer that can only be trusted.

## Where to start

`project_status.md` has the current state and the ordered next steps, and
**"What the player actually does"** describes the loop they rely on — worth
reading before changing anything near navigation or teleport.

The change that would most improve play is **teaching the map scale by
teleporting rather than flying**. The story objective is a minimap marker with
no coordinate-table entry; converting it needs a scale the calibrator learns
from movement, and the player cannot fly. Teleport is movement the guide
controls, so a few short teleports in known directions should teach it, saved
per map profile.

The largest untouched piece is **Dragon Adventure story subtitles**: the text is real UTF-16LE
in the disc's `TXT-US-*` files, on-screen prose is demonstrably readable from
RAM, and the menu subtitles prove the mechanism. The open question is only how
to tell which line is currently displayed, since a cutscene has no cursor.
`docs/memory-map.md` describes the method for settling it.

## Licensing

Third-party components and their licences are listed in `THIRD-PARTY.txt` and
the `licenses` folder.
