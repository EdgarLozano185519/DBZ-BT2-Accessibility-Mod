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
  `01 80 00 00 00 00 00 C4 E1 06 53 53` at `0x00533D60`

Match markers as a **prefix**. The main menu's name is `mc_menu_lineanime`; an
exact comparison against a 16-byte window clipped the trailing "e" and failed.

A readable marker beats a state number because it can be checked rather than
trusted. Note the static string table at `0x00428280` holds these same names on
*every* screen -- only the copies in the dynamic region are screen-specific.

**Confidence.** The main menu marker held the same address across 19 captures
and survived a full out-and-back transition. Options and Dragon Library rest on
a **single visit each**; their addresses could shift between visits and have not
been re-verified.

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

## Screens seen but not mapped

- **Options** -- a vertical list, not a carousel: Save/Load, Controller, Screen,
  Sound, EXIT. Labels read from a screenshot and independently corroborated by
  its sprite names (`mc_icon_saveload`, `mc_icon_controller`, `mc_icon_screen`,
  `mc_icon_sound`). **Cursor address not found.**
- **Dragon Library** -- detected only.
- **Ultimate Battle Z** -- not detected at all. The announcer correctly says
  "Unknown screen" there, which is the intended behaviour: naming a screen it
  cannot read would be worse than admitting it.

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

Captures land in `reference/probe/`, which is git-ignored. Game memory must
never be committed.

## Known gaps

- Options, Dragon Library and every other submenu need cursor addresses.
- Ultimate Battle Z and the rest are not detected at all.
- The announcer says "Unknown screen" on every screen *transition*, not only on
  genuinely unmapped screens, because no marker matches while one screen is
  unloading and the next has not loaded. It needs a delay before speaking that.
- On re-entering a screen the cursor briefly reads 0, so the first option can be
  announced spuriously before the correct one. The cursor needs a moment to
  settle after a screen change.
- Nothing reads the 2,601 story strings yet.
