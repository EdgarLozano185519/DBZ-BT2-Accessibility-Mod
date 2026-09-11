# DBZ BT2 Accessibility Guide

Screen reader support for **Dragon Ball Z: Budokai Tenkaichi 2** (PlayStation 2,
USA release), played in the PCSX2 emulator. It speaks menus aloud and gives
spoken navigation guidance in Dragon Adventure, so the game can be played
without sight.

It reads the game's memory while it runs. It does not modify the game, the disc,
or your saves.

**Windows x64.** The release version of this build is in `BUILD-INFO.json`;
quote it when reporting a problem.

This package contains **no game, BIOS, emulator, save data, memory cards, save
states, recorded game images, RAM dumps, or prefilled map atlas**. You supply
your own. The guide uses the memory card you configured in PCSX2 — it does not
swap memory cards or hand you unlocked progress, and the optional teleport
changes your live coordinates only when its pause and validation checks pass.

---

# For players

## What you need

- **Windows 10 or 11, 64-bit**, with .NET Framework 4.8 (present on most systems)
- **PCSX2**, your own installation. Tested with 2.9.32
- **A PS2 BIOS dump** and your own copy of the game: **SLUS-21441**, CRC
  **FE961D28** (USA). Other regions are not supported
- **NVDA**, if you use it. Windows' own SAPI voice is the automatic fallback

No Python, terminal or runtime install is needed. Everything is inside the guide.

## Running it

1. Extract the whole folder, keeping `worker` beside `DBZ BT2 Guide.exe`.
2. Set up PCSX2 normally first: BIOS, controller, memory card.
3. Open **DBZ BT2 Guide.exe**. On first run, Settings searches for your PCSX2
   and your game; pick one if several are found, then Save. **Browse** covers
   a folder it did not think of.
4. Choose **Open game**. With PCSX2 closed, this switches on the PINE
   connection in that PCSX2's own settings, after backing up its `PCSX2.ini`.
5. Choose **Start guide**, then load or begin your Dragon Adventure game.
   **Alt+Tab** returns you to the game.

You can also launch the game yourself and then press Start guide. Guidance
pauses whenever another window has focus, so your screen reader is never
talked over.

## The guide's own window

Standard Windows controls: **Tab** moves between them, **Enter** or **Space**
activates. **Start guide** and **Stop guide** do what they say; closing the
window stops the worker too. **Speak guide messages** turns its speech off if
you would rather read it, and **Latest message** and **Message history** hold
what was said. Speech goes through NVDA when it is running, else Windows SAPI.
NVDA is not bundled.

## What it does today

**Menus speak.** Moving the cursor announces the highlighted option on:

- the **title screen** and the **main menu**, all ten options
- **Options** — Save and Load, Controller, Screen, Sound, Exit
- **Select Scenario** — every scenario on the disc, by name
- **Story Events** — each event as the screen writes it, "06 Training with
  King Kai", including when the list scrolls; F12 reads the synopsis
- **Game Level** — the event it is for, then Level 1, 2 or 3
- **Character Select** in Dueling, both players, and the **Dragon Tournament**
  entry strip — every fighter, read from the game's own text
- **The Item Shop** — Buy and Sell, every Z-item in every tab, the how-many
  picker after X ("times 1", "times 2"), and Baba's refusal when you cannot
  afford it
- **Evolution Z** — its menu, the character row, the **Z Item List** across
  five tabs as "Health +1, 1 of 155" (unowned items read "???" as drawn),
  **Z Item Fusion** with numbered rows and the first plate after X, King Kai's
  refusal of a bad combination, and the **Explanation box** behind Square

Character and item names come from the text the game is drawing, so every one
on the disc is covered without a list. Scenario names are pictures on screen,
but the game keeps its own list of them and all of it ships with the guide,
keyed to the game's own numbering, so a newly unlocked scenario reads at once.

Screens it recognises but has not mapped are named and then stay quiet; screens
it does not recognise say "Unknown screen." Where the game keeps two copies of
a cursor, both are read; if they disagree it says so rather than name the wrong
row. "Looking for the subtitles" or "Looking for the menu" means something has
moved and it is searching; it carries on by itself. "Scenario 5 of 6, name not
known" should never happen and is worth reporting.

**F12 speaks the game's own text on any screen** — the character's line for a
main menu option, the instruction on Game Level, whatever is written on a
screen the guide was never taught. It is on a key so browsing stays quick.

**The story speaks by itself.** In a cutscene each box of dialogue and
narration is read as it appears; advance the scene as normal. Only cutscene
text is read this way, so an unmapped menu stays quiet, and notices such as
"MEMORY CARD slot 1" are on F12 instead. It waits for a line to settle before
speaking, and each new line interrupts the last so you always hear the box you
are on; say so if you would rather hear every line in full. If you ever hear a
line that is not on screen, most likely just after a cutscene ends, please
report it.

**Dragon Adventure navigation.** The guide picks the story objective off the
live minimap, tracks your position, and steers you with stereo tones and
spoken messages. It needs the game window **visible in windowed mode with the
original HUD**; texture or HUD replacements are untested.

With the game focused:

- **F12** — the game's own text for this screen
- **N** / **B** — step through the map's destinations: the numbered points,
  then **the other character** if one is on the map, then **the story
  marker** once the map is calibrated
- **G** — how far the chosen destination is and which way to turn, as a turn
  in your own terms ("hard right, 1691 units"), or a compass bearing when your
  heading cannot be read, and it says which
- **T** — teleport to the chosen destination. **Pause PCSX2 first**; the guide
  says so if you forget, reads every write back, and rolls back a failure
- **C** — calibrate this map: six short announced hops, each one "pause, wait
  for Moved, unpause", ending exactly where you started. Saved per map. Press
  C again to stop; it refuses, and says why, if it has nowhere safe to hop
- **R** — repeat the current destination
- **L1** on a detected DualSense — same as T
- **S**, **F**, **U** — record what a place turned out to be

The tones keep following the story objective whatever you choose; choosing
changes only where T goes.

**Reaching a story event**, on a calibrated map: **N** until "the story
marker", pause PCSX2, **T**, unpause, then the action button. Before C has run,
the marker is not offered, so teleport to the numbered points in turn and try
the action button at each; there are usually fewer than ten.

**A character who runs from you** — Android 20 in the Android Saga — is not
caught that way: the story marker is his picture, T lands you near him, and
near is what makes him fly off. Choose **the other character** instead. That
comes from the game's memory, lands you on him exactly, and the scene starts
on its own, with no button. Confirmed in play 2026-09-10.

When the destinations change under you, as finishing an event does, it says
"Destinations changed" and describes the new set. When it must use a map's
destinations without being able to confirm they belong to this map, it says so
once.

## Maps and progress

The atlas starts empty and learns maps as you visit them. New maps get a
descriptive label and a number, not the game's names; to rename one, stop the
guide, select it under **Discovered map**, type a name and choose **Save map
name**. Learned maps, settings and logs live in `%LOCALAPPDATA%\DBZ BT2 Guide`,
outside this folder.

## What it cannot do yet

Silence from a screen reader is indistinguishable from "working, nothing to
say", so:

- **The story marker is a destination only on a calibrated map.** C has been
  run on one map; whether it holds everywhere is not yet known
- **T is refused while the objective is unresolved**, even with a destination
  chosen from memory. If the tones go quiet, T goes with them
- **Several characters on one map**: the guide offers whichever one the game
  handled last and cannot yet say which
- **Dragon Library**'s entries, **Ultimate Battle Z**, **Data Center** and
  the battle menus are not read. Battles are not accessible beyond the game's
  own audio
- **Evolution Z**: a successful fusion has not been seen; Z Item Collection's
  equipment view and the password screen are not read; Fusion rows say
  "row 5" rather than "5 of 38"
- **Item Shop**: prices, the Zeni you would have left and your balance are
  not spoken; the sale itself after the picker, and the Sell side's
  questions, have not been seen
- **Scenario descriptions** are not read
- **The guide cannot tell when text stops being on screen**; three checks
  make a wrong read unlikely, and a line heard with nothing on screen is
  worth reporting
- An ambiguous objective may stay unconfirmed; it says so rather than guess
- Not yet tested on a separate, clean Windows machine

## If something goes wrong

- **Waiting for a connection** — close PCSX2 normally, confirm the right copy
  in Settings, then Open game so the guide can switch PINE on
- **Silent** — return focus to the game, check *Speak guide messages*, and
  read the Message history
- **The runtime is missing** — extract the whole package again, with `worker`
- **The worker stopped** — the window keeps the error; Start guide retries.
  An unrecoverable startup error is written to `logs\last-worker-error.txt`

Every session leaves a transcript in `%LOCALAPPDATA%\DBZ BT2 Guide\logs`.
When reporting a problem, include the release version, your PCSX2 version,
where you were, what you did and expected, and that log; it may contain your
map names and local paths. **Do not send game dumps, BIOS files or saves.**

## About this build

**2026.09.10-r1** offers **the other character** as a destination on every
world map, not only on maps with no destination table, and fixes the marker
finder rejecting a character's arrow-shaped marker when it points sideways,
which had silenced the tones and T. Built for the Android Saga's "Doctor
Gero's Lab", where Android 20 flees whenever you come within about a thousand
units; landing on his exact position starts the scene by itself. Both parts
heard in play the same night.

**2026.09.09-r2** adds Evolution Z: the menu, the character row, the Z Item
List across five tabs with each row placed as "3 of 194", Z Item Fusion with
its first plate, and the Explanation box. All heard in play the same evening.

**2026.09.09-r1** adds the story event list and has Game Level name the event
it is for, both from the text the game draws. It also stops "Select Scenario"
being announced over the event list.

**2026.09.08-r5** adds the Item Shop, heard in play the same night, and stops
"Select Scenario" being announced over the shop. r2 the same day added maps
with no destination table; r3 and r4 were never handed out.

**2026.09.08-r1** added the two character selects and stopped "New Game"
being announced over screens that were not the title.

Releases since r1 omit the 44 `api-ms-win-*.dll` stubs that 2026.09.05-r4
carried; they forward to a runtime that ships inside Windows 10 and 11.

The `source` folder holds the runtime and interface source. Third-party
notices and versions are in `THIRD-PARTY.txt` and the `licenses` folder.

## Useful links

- PCSX2 setup — <https://pcsx2.net/docs/setup/running/>
- PINE setting labels, from the PCSX2 2.6.3 source —
  <https://github.com/PCSX2/pcsx2/blob/v2.6.3/pcsx2-qt/Settings/AdvancedSettingsWidget.ui>
- NVDA — <https://www.nvaccess.org/>

---

# For developers

## How it fits together

- **`DBZ BT2 Guide.exe`** — a C# WinForms interface (`source/tools/ui/
  GuideDesktop.cs`). Standard Windows controls, so screen readers handle it.
- **`worker/guide-worker.exe`** — a PyInstaller bundle of
  `source/tools/guide_host.py`. The UI starts it and reads its output.
- **`source/tools/bt2/`** — the guide itself. `guide.py` holds the main loop,
  `menus.py` reads menus, `story.py` reads the prose the game is displaying,
  `vision.py` reads the HUD from captured frames,
  `memory.py` and `scan.py` find structures in PS2 RAM, `speech.py` and
  `speech_output.py` talk to NVDA with a SAPI fallback.
- **`source/tools/pine_client.py`** — PCSX2's PINE IPC protocol: arbitrary reads
  and writes of emulated PS2 memory over a local socket.

Menu reading runs at the one point in `guide.py` where navigation guidance is
suspended -- outside Dragon Adventure, which is exactly when the player is in a
menu. The two can therefore never talk over one another. Story reading runs
there too, but only when the menu reader does not recognise the screen, which
is where a cutscene lives.

## The thing to understand first

**BT2's menu labels are pre-rendered artwork, not text.** Nothing in memory
spells "Dragon Adventure". The game stores the *index* of the highlighted
option, so the words come from tables in `bt2/menus.py` -- the only place that
text exists, and the only thing that can be translated.

**Prose is the opposite.** On-screen subtitles are held as verbatim UTF-16LE, so
those are read from the game rather than authored. So are the character
names on the select screens: the game draws them as text, and its own pointer
to that text follows the highlight, which is why those screens have no cursor
address and no table. Check for that before hunting a cursor on any screen.

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
  poisons the correlation while the run still looks clean. Give each screen
  its own `--prefix`; the default names are the Select Scenario archive that
  `test_menus.py` checks.
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
- **`rowscan ADDR... [--capture]`** — for when the candidates are already known
  and the question is what they *mean*. Reads them at 10 Hz and photographs the
  screen the moment they settle on a new value, so every row the player passes
  through is recorded beside a picture of it. Seconds and kilobytes, where
  `positionscan` costs minutes and 31 MB per press; `--capture` adds the full
  RAM as well when a new address has to be searched for. It writes `row*` and
  never touches the `posn*` archive.
- **`watch ADDR...`** — poll addresses live to see which hold steady.
- **`recorrelate`** — re-analyse the last capture from disk.

`source/tools/extract_text.py` pulls the disc's story text offline — 553
`TXT-US-*` files, 2,601 text boxes — with no emulator and no player involved.
Each file is a scene and its slots are in the order the game shows them, so a
box found in RAM identifies both the scene and how far through it the game is.
That is the filter that made the subtitle search tractable.

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
- **A marker's exclusivity is only as good as the route the captures took.**
  Every capture of a screen outside Dragon Adventure had been taken in a
  session that never entered it, so "this marker is absent there" was never
  evidence of anything — and a Dragon Adventure marker that stays resident
  afterwards took the main menu's name away in play. Check a marker against
  captures reached the way the player reaches the screen.
- **A menu of N entries cannot distinguish its cursor from any counter of
  period N.** A two-entry list shipped an address that was never an index; it
  fitted six cued presses, three captures and a held-out seventh. Where a menu
  is short, say so beside the address and re-derive when the list grows.
- **For a list that grows, look for the list, not just the cursor.** The game
  has to know which items it is showing, and that array survives insertions
  where a row number does not — so names hung off it never shift. Search it by
  *shape*, the shorter list being a subsequence of the longer, and require the
  region to change between the two.
- **A search can only find what it asked for.** Three searches concluded no
  scenario identity existed. All three asked for something that changes as the
  cursor moves; the answer was an array that does not, so none of them could
  have found it. When a search comes back empty, check the question before
  believing the answer.

## Where to start

`project_status.md` has the current state and the ordered next steps, and
**"What the player actually does"** describes the loop they rely on — worth
reading before changing anything near navigation or teleport.

**The map scale is taught by teleporting rather than flying** -- `bt2/mapcal.py`,
on the C key, working in play since 2026-09-07. The story objective is a minimap marker with no coordinate-table
entry, so converting it needs a scale the calibrator normally learns from
movement, and the player cannot fly. Teleport is movement the guide controls.
Six commanded hops produce the same observations, the last one is the trip home,
and the answer is saved per map profile. It reuses `calibration.py`'s solver and
its confidence test unchanged; what it owns is deciding which white blob is the
arrow, which the usual identifier settles from drift the player has to produce.
`test_mapcal.py` covers it offline, no emulator needed.

**Story subtitles now work** and the way they were found is worth reading
before hunting anything else: `docs/memory-map.md`, under *Story text*. The
short version is that the game keeps a pointer to the string it is drawing, at
`0x008C6244`, so no text has to be transcribed and nothing is tied to English.

Two things there are worth internalising. The corpus extracted from the disc is
a **search** tool, not a runtime dependency -- it makes "is this a real line of
dialogue" answerable offline, which is what made the search tractable. And two
byte-sized candidates found first matched all eight derivation captures, were
the only two such bytes in 31 MB, and were still **wrong**; they disagreed with
the screen on the very next scene. Verify on a transition you did not derive
from, every time.

`story_probe.py` is the tool: `capture` records RAM and a screenshot each time
the text box changes while the player simply plays, `compare` sorts addresses
into display slots and resident blocks, and `follow` drives the shipped reader
from a terminal. `test_story.py` covers the reader offline, no emulator needed.

## Licensing

Third-party components and their licences are listed in `THIRD-PARTY.txt` and
the `licenses` folder.
