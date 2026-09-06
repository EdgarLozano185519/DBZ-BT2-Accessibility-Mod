# DBZ BT2 memory map (SLUS-21441, CRC FE961D28)

Addresses are PS2 EE physical addresses, read over PCSX2's PINE link. Every
entry here was confirmed against the running game, never inferred. Each one
records how it was verified so a later reader can judge it.

## Why the mod reads indices, not text

The game's menu labels are **pre-rendered artwork, not strings**. Verified from
the disc image:

- `SLUS_214.41` contains no English UI text in ASCII or UTF-16.
- The UI archives in `ZS2US_2.AFS` (`Menu.pak`, `Title.pak`, `Option.pak`,
  `DAdventure.pak`, `UBattle.pak`, `IShop.pak`, `DCenter.pak`, …) contain no
  readable strings at all.
- The executable instead holds sprite names indexed by number:
  `mc_item_name_%d`, `mc_chara_plate_%d_e`, `mc_title_text`,
  `mc_dummy_rule_text%d`.

So there is nothing in memory spelling "New Game". What the game keeps is the
*index* of the highlighted option, which is what these addresses hold. Spoken
labels have to come from our own table keyed by that index.

Story and tutorial text is the exception: it *is* real UTF-16LE text, in the
553 `TXT-US-*` files inside `ZS2US_1.AFS` (2,601 strings). That is a separate
route, still to be built.

## Title screen: New Game / Load Game spinner

A one-at-a-time spinner cycled with up and down. Two options.

- `0x00533A73` (byte) — **cursor index x 2**. `0` = New Game, `2` = Load Game.
- `0x00533A83` (byte) — mirror, identical values.
- `0x00533A93` and `0x00533AA3` (bytes) — same signal offset by two: `2` = New
  Game, `4` = Load Game.

The stride-2 encoding is unexplained so far. It may be a byte offset into a
table of 16-bit entries, or a sprite id. Confirming that needs a menu with more
than two options; do not assume `index * 2` generalises until then.

**Verification.** Fourteen paired captures of full EE RAM and the game window,
grouped by the label's pixels (`menu_probe.py autoscan`). `0x00533A73` matched
the on-screen option in all 14, including the two frames where the attract demo
had cut in. A live re-test with a stability guard -- reading the address either
side of each screen capture and discarding frames caught mid-change -- agreed on
16 of 17 stable frames. The single outlier read a stable 0 while the capture
showed Load Game, with a transition detected two samples later, consistent with
`PrintWindow` returning a stale frame.

**Ruled out.** `0x00533FF0` and `0x00534030` survived an early five-snapshot
search and looked convincing -- stable, and correct whenever checked by hand --
but disagreed with the screen on samples 3 and 4 of the autoscan. They are not
the cursor. `0x00AA1290` and `0x00AA56F0` failed the same way. Coincidence
across a handful of snapshots is easy in 31 MB; only the paired screen-and-RAM
correlation settled it.

**Known gap.** During the attract demo `0x00533A73` also reads `0`, so this
address alone cannot tell "New Game is selected" from "the demo is playing".
A separate screen-state indicator is needed before anything is announced --
otherwise the mod will happily say "New Game" over a cut-scene.

## Method

`source/tools/menu_probe.py` is the tool used above.

- `snap NAME` / `find A B C --sequence=0,1,0` — snapshot RAM by hand and search
  for a value sequence. Workable, but every pause to confirm what is on screen
  is a pause the attract demo can interrupt.
- `autoscan --samples=N --interval=S` — **preferred.** Captures RAM and the
  screen together while the player moves the cursor freely, groups the samples
  by the label's pixels, and reports which addresses track those groups. No
  turn-by-turn coordination, and no OCR: the labels are stylised artwork, which
  general text recognition handles badly, but identical frames are pixel
  identical, which makes grouping exact. Same-option frames measure 0.00 apart
  and different options 21.41, against a tolerance of 4.0.
- `recorrelate` — re-analyse the last autoscan from disk. Capturing costs a live
  session; the analysis should never require repeating it.
- `watch ADDR...` — poll addresses live to see which hold steady between presses.

Snapshots are 31 MB and take 0.7 s over PINE, with PCSX2 unaffected. Note that
`bt2/scan.py` warns that reading all of RAM starved the VM and correlated with
hangs; that concerns the guide's continuous polling during play, not a one-off
diagnostic read.

Captures land in `reference/probe/`, which is git-ignored. Game memory must
never be committed.
