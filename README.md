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
3. Open **DBZ BT2 Guide.exe**. On first run its Settings window searches for
   your PCSX2 and your game: running instances, installed and portable copies,
   PCSX2's own game libraries, the common game folders and your local drives.
   Pick one only if several are found, then Save. **Browse** is there for a
   folder it did not think of.
4. Choose **Open game**. With PCSX2 closed, this switches on the connection the
   guide needs (PINE) in that installation's own settings, keeping whatever
   port it is configured for and saving a backup of your `PCSX2.ini` first.
   Portable marker files and the `-portable` launch mode both work.
5. Choose **Start guide**, then load or begin your own Dragon Adventure game.
   **Alt+Tab** returns you to the game.

You can also launch the game yourself in PCSX2 and then press Start guide; the
Settings paths only matter for the Open game button.

Guidance pauses whenever another window has focus, so you can use your screen
reader normally without the guide talking over it.

## The guide's own window

It is built from standard Windows controls, so a screen reader handles it
normally. **Tab** and **Shift+Tab** move between controls; **Enter** or
**Space** activates a button.

- **Start guide** starts the companion. **Stop guide** silences and stops it
  while leaving the game open. Closing the guide also stops its worker.
- **Speak guide messages** turns the guide's own speech off if you would rather
  read it.
- **Latest message** and **Message history** keep what was said available to
  read back at your own pace.

Speech goes through **NVDA** when it is running, and falls back to Windows SAPI
automatically. **NVDA is not bundled** — install it yourself if you want it.

## What it does today

**Menus speak.** Moving the cursor announces the highlighted option on:

- the **title screen** — New Game, Load Game
- the **main menu** — all ten options
- **Options** — Save and Load, Controller, Screen, Sound, Exit
- **Select Scenario**, the Dragon Adventure scenario list — Saiyan Saga, Tree
  of Might, Lord Slug and Fateful Brothers, chosen with Up and Down
- **Game Level**, the difficulty chooser reached after picking a story event in
  Dragon Adventure — Level 1, 2 or 3, chosen with Left and Right

The scenario names are pictures rather than words in the game's memory, so each
one has to be seen once and written down by hand. The guide asks the game
*which* scenario each row is, so the names it already knows stay right when you
unlock something new — only the new one is unnamed, and it says **"Scenario 4
of 5, name not known."** rather than guessing. Please report it when you hear
that: it takes about a minute to add, and you only ever hear it once per
scenario.

Screens it recognises but has not mapped are named and then stay quiet; screens
it does not recognise say so, rather than guessing. Where the game keeps two
copies of the cursor, both are read, and if they ever disagree it says so and
leaves the row unnamed rather than naming the wrong option.

A few things you may hear it say, and what they mean:

- **"Unknown screen."** — it does not recognise where you are, so it will not
  guess. F12 still reads whatever is written there
- **"Looking for the subtitles."** or **"Looking for the menu."** — the game
  has put something somewhere new and the guide is searching for it. It takes
  a moment and then carries on
- **"Scenario 4 of 5, name not known."** — you have unlocked a scenario whose
  name the guide has never been shown. Everything else in the list still reads
  correctly
- **"the two copies of the cursor disagree"** — the guide can see the screen
  but not which row you are on, so it will not name one. F12 still works

**F12 speaks the game's own text, on any screen.** On the main menu, the
character's spoken line for the highlighted option. On Game Level, the
instruction line. On a screen the guide has never been taught, whatever is
written there. It is on a key press so that browsing stays quick. If the text
has moved since it was last recorded, F12 says "Looking for the subtitles",
finds it again, and carries on; where there is genuinely nothing written, it
says so rather than staying silent.

**The story speaks by itself.** In a Dragon Adventure cutscene, each line of
dialogue and narration is read aloud as the game puts it on screen. There is no
key to press — advance the scene as you normally would and the guide reads each
text box once.

Only cutscene text is read this way. On a menu the guide has not been taught it
stays quiet rather than reading out the flavour text under each option, which
is what F12 is for. Notices like "MEMORY CARD slot 1" go with the menus: press
F12 to hear one.

This is the game's own text, taken from the pointer the game itself uses to
draw it, so nothing has been transcribed and nothing is tied to English.

Two things to know. It waits for a line to be stable before speaking, so there
is a fractional pause before each box — that pause is deliberate and stops a
half-drawn line being read. And each new line **interrupts** the one before, so
that you always hear the box you are on rather than the one you have left; if
you would rather hear every line in full even when it falls behind, say so and
it can be changed.

**If you ever hear a line that is not on screen** — most likely just after a
cutscene ends — please report it. The guide cannot yet tell "text is being
displayed" from "text was displayed a moment ago", and that is the one case
that has never been captured.

**Dragon Adventure navigation.** The original guidance: it picks an objective
from the live minimap, tracks your position, and uses stereo direction and pitch
plus spoken messages to steer you there.

Because it reads the minimap off the screen, it needs the game window
**visible and the minimap unobstructed**. Start in **windowed mode with the
original HUD**; texture replacements and HUD modifications are untested and
may stop it working.

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

**Once the map is calibrated, the story marker is the last item in that cycle.**
Keep pressing N past the numbered points and you reach "the story marker";
choose it and T goes there. Before calibration it is not offered, because until
then it is a picture on the minimap with no known place.

Teleporting still requires pausing PCSX2 by hand first: writes race the
emulator's CPU thread otherwise. The guide says so if you press T without
pausing, every write is read back to confirm it, and a failed write is rolled
back.

**C teaches the map its scale, so T can reach the story marker.** Confirmed in
play on 2026-09-07. The red story marker is a picture on the minimap, not an
entry in the map's coordinate table, so turning it into somewhere teleport can
write needs the minimap-to-world scale. That scale is normally learned from
flying, which is the one thing this mod cannot ask for. C learns it from
teleporting instead.

Press **C** on the world map. It makes six short hops and puts you back exactly
where you started, and it tells you what to do at each step: pause PCSX2, wait
for "Moved", unpause, and again. Press C at any point to stop; it takes you home
before it does. The scale is saved per map, so it is a one-time cost.

It will not start if it has nowhere safe to hop — off the edge of the map, or
onto another destination. Standing on a destination yourself is fine: that is
where teleporting leaves you, and the hops go around it. If it refuses it says
which of the two got in the way, and teleporting somewhere else and pressing C
again usually settles it.

If it cannot tell the arrow from the map's clouds it says that too, and learns
nothing, rather than saving a scale it is not sure of.

**Reaching a story event.** On a calibrated map:

1. **N** until you hear **"the story marker"** — it is the last item.
2. **Pause PCSX2**, press **T**, then unpause. You are standing on it.
3. Try the action button.

Before C has run on a map, the story marker is not offered and the older loop
is what works — press **N** or **B** through the numbered points, **G** to hear
how far each is, teleport to each in turn and try the action button until one
of them is the event. It is trial and error, and there are usually fewer than
ten places to try.

Both need no flying, which is the point: they exist because moving accurately
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

## Maps and progress

The atlas starts **empty** and learns maps as you visit them. A change of
lighting alone does not create a new map.

A newly discovered map is given a descriptive label and a number. Those are
**descriptions, not the game's official names** — they are what the guide could
tell about the place, not what it is called. To rename one: stop the guide,
select it under **Discovered map**, type your preferred name in **Map name**,
and choose **Save map name**. Some maps stay temporary until their identity can
be confirmed. Learned maps are stored with your settings and logs, outside this
folder — see *If something goes wrong*.

## What it cannot do yet

Being honest about the limits, because silence from a screen reader is
indistinguishable from "working, nothing to say":

- **The story marker can only be teleported to on a map you have calibrated.**
  It exists only as a marker drawn on the minimap, so turning it into a place
  needs that map's scale — which is what **C** measures. Until you run C on a
  map, the trial-and-error loop above is what works there. C has been run on
  one map so far; whether it holds on every map is not yet known
- **The story event list does not speak.** The scenario list before it now
  does, and the difficulty screen after it does, but choosing the individual
  event between them is still done blind
- Dragon Library is named but its entries are not read. Ultimate Battle Z, the
  item shop, character select and battle menus are not recognised at all
- **The scenario descriptions are not read.** The introduction to each Dragon
  Adventure scenario sits in the game's memory and can be found. The guide now
  knows which scenario is highlighted, so this has become possible; what is
  left is working out where each description begins
- **The guide cannot tell when text stops being on screen.** It reads the
  pointer the game uses to draw text, and that pointer keeps its last value
  after a scene ends. Three checks make a wrong read very unlikely, but the
  one situation that has never been captured is a battle with no text box
  showing. If you hear a line that is not on screen, please report it
- **Battles are not accessible** beyond the game's own audio
- **The event name is not read on Game Level.** F12 used to announce one, and
  it was the first event's name whatever you had picked — so it has been
  removed. The instruction line beside it is correct and is still read. Naming
  the event properly needs the story event list mapped first
- If the guide cannot find any text, F12 says so rather than reading nonsense
- Navigation is a playtest of Dragon Adventure, not whole-game accessibility.
  Unfamiliar maps still need wider testing
- An **ambiguous objective may stay unconfirmed**. The guide says so rather than
  inventing a route
- This build has **not been tested on a separate, clean Windows machine**

## If something goes wrong

- **Waiting for a connection** — close PCSX2 normally, confirm the right copy is
  chosen in Settings, then choose Open game so the guide can switch PINE on
- **Silent** — return focus to the game, check *Speak guide messages*, and read
  the Message history
- **The runtime is missing** — extract the whole package again, with its `worker`
  folder
- **The worker stopped** — the window keeps the error available; choose Start
  guide to retry. Runtime errors are retried without closing the guide, and an
  unrecoverable startup error is written to `logs\last-worker-error.txt`

Settings, logs and learned maps live in `%LOCALAPPDATA%\DBZ BT2 Guide`, kept
separate from this extracted folder and from PCSX2's own saves.

When reporting a problem, include the release version, your PCSX2 version, the
map or chapter you were on, what you did and what you expected, and the
relevant log. Review logs before sharing; they can contain your map names and
local paths. **Do not send game dumps, BIOS files or saves.**

## About this build

This release omits the 44 `api-ms-win-*.dll` compatibility stubs that release
2026.09.05-r4 carried. They forward to the Universal C Runtime, which ships
inside Windows 10 and 11 — and Windows 10/11 x64 is what this guide requires —
so nothing a supported system needs was lost.

The `source` folder holds this guide's runtime and interface source, for
inspection. Third-party notices and versions are in `THIRD-PARTY.txt` and the
`licenses` folder.

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
