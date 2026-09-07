"""Find the memory that tracks a menu cursor, by value sequence rather than diff.

BT2's menu labels are pre-rendered artwork, so nothing in memory spells "New
Game".  What the game must keep is the *index* of the highlighted option, and
that is what this hunts.

A plain before/after diff is close to useless here: thousands of words change
every frame for timers, animation and random numbers.  Instead this captures a
snapshot per cursor position and then asks which addresses follow the sequence
the cursor followed -- stepping by exactly one each time.  Frame noise almost
never counts 0, 1, 2 in lockstep with a person pressing a button, so the search
filters itself.

Usage, one snapshot per cursor position:

    python menu_probe.py snap pos0        # on the first option
    python menu_probe.py snap pos1        # after pressing down once
    python menu_probe.py snap pos2        # after pressing down again
    python menu_probe.py find pos0 pos1 pos2

Each snapshot also saves a screenshot, so which option was actually on screen
can be confirmed afterwards instead of trusted from memory.

Snapshots land in reference/probe/, which is git-ignored -- they are captures
of game memory and must never be committed.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

from pine_client import PineClient

# EE main RAM. A sweep at 1 MB granularity found live data only below about
# 0x00D00000 while the menu was up, so the default stops at 0x01000000 and
# --full opts into the rest. Reading all 32 MB in one go is what scan.py
# documents as having starved the VM and correlated with emulator hangs.
DEFAULT_BASE = 0x00100000
DEFAULT_END = 0x01000000
FULL_END = 0x02000000

# One PINE request per chunk, with a pause between them so the emulator keeps
# getting scheduled while a capture is in flight.
CHUNK_BYTES = 1024 * 1024
CHUNK_PAUSE = 0.01

# Repository root, alongside the source and worker folders -- matching where a
# reference folder is expected to live, and covered by .gitignore.
STORE = Path(__file__).resolve().parents[2] / "reference" / "probe"


def _capture_screen(path: Path) -> bool:
    """Save what was on screen, so the snapshot's meaning can be verified."""
    try:
        from bt2 import vision

        vision.capture_game_window().save(path)
        return True
    except Exception as error:  # A capture failure must not lose the RAM snapshot.
        print(f"  (screenshot unavailable: {type(error).__name__}: {error})")
        return False


def snap(name: str, end: int = DEFAULT_END) -> int:
    STORE.mkdir(parents=True, exist_ok=True)
    base = DEFAULT_BASE
    size = end - base

    client = PineClient(timeout=15.0)
    try:
        started = time.monotonic()
        blocks = []
        for chunk_address in range(base, end, CHUNK_BYTES):
            chunk_size = min(CHUNK_BYTES, end - chunk_address)
            blocks.append(
                client.read_aligned_range(chunk_address, chunk_size, allow_large=True)
            )
            time.sleep(CHUNK_PAUSE)
        elapsed = time.monotonic() - started
    finally:
        client.close()

    data = b"".join(blocks)
    if len(data) != size:
        print(f"FAILED: expected {size} bytes, got {len(data)}")
        return 1

    (STORE / f"{name}.bin").write_bytes(data)
    shot = _capture_screen(STORE / f"{name}.png")

    print(f"Snapshot '{name}': {size / 1048576:.0f} MB from "
          f"0x{base:08X}-0x{end:08X} in {elapsed:.1f}s.")
    if shot:
        print(f"  Screenshot saved beside it as {name}.png.")
    return 0


def _views(data: bytes) -> list[tuple[str, int, np.ndarray]]:
    """Interpret the block as 8-, 16- and 32-bit values at every alignment."""
    raw = np.frombuffer(data, dtype=np.uint8)
    views: list[tuple[str, int, np.ndarray]] = [("u8", 0, raw)]
    for label, dtype, width in (("u16", np.uint16, 2), ("u32", np.uint32, 4)):
        for offset in range(width):
            usable = (len(raw) - offset) // width * width
            views.append(
                (label, offset, raw[offset : offset + usable].view(dtype))
            )
    return views


def find(names: list[str], sequence: list[int], limit: int = 40) -> int:
    """Report addresses whose values track ``sequence`` across the snapshots.

    The sequence is the cursor position each snapshot was taken at, so a
    two-option spinner cycled with down presses gives 0, 1, 0.  Matching a
    shape rather than a rising count matters: a menu that wraps never counts
    upwards, and requiring it to would find nothing.

    Two readings are reported separately.  An *absolute* match stores the index
    itself, so its values equal the sequence exactly.  A *relative* match moves
    in the same shape from some other base -- a menu numbered from one, or a
    scroll offset -- and is still worth seeing.
    """
    if len(names) < 2:
        print("FAILED: need at least two snapshots to compare.")
        return 1
    if len(sequence) != len(names):
        print(f"FAILED: {len(names)} snapshots but {len(sequence)} sequence values.")
        return 1

    blocks = []
    for name in names:
        path = STORE / f"{name}.bin"
        if not path.exists():
            print(f"FAILED: no snapshot named '{name}'. Take it with: snap {name}")
            return 1
        blocks.append(path.read_bytes())

    if len({len(b) for b in blocks}) != 1:
        print("FAILED: snapshots cover different ranges; retake them the same way.")
        return 1

    print(f"Comparing {len(names)} snapshots of {len(blocks[0]) / 1048576:.0f} MB")
    print(f"  snapshots: {', '.join(names)}")
    print(f"  cursor was at: {sequence}\n")

    # Interpret every snapshot the same way once, then compare view by view.
    interpretations = [_views(block) for block in blocks]
    widths = {"u8": 1, "u16": 2, "u32": 4}

    absolute: list[tuple[int, list[int]]] = []
    relative: list[tuple[int, list[int]]] = []

    for position, (label, offset, first) in enumerate(interpretations[0]):
        others = [other[position][2] for other in interpretations[1:]]

        # Narrow with pairwise equality first. Comparing in the value's own
        # unsigned type keeps this cheap -- widening 31 MB to int64 would cost
        # 250 MB per snapshot to learn nothing extra -- and "equal where the
        # cursor was equal, different where it differed" already discards
        # almost everything, including the frame noise a plain diff drowns in.
        candidates = np.ones(len(first), dtype=bool)
        for other, value in zip(others, sequence[1:]):
            if value == sequence[0]:
                candidates &= other == first
            else:
                candidates &= other != first

        hits = np.flatnonzero(candidates)
        if hits.size == 0:
            continue

        # Confirm the surviving few exactly, in Python integers so that a
        # decreasing step cannot wrap around in unsigned arithmetic.
        width = widths[label]
        for index in hits:
            values = [int(first[index])] + [int(o[index]) for o in others]
            address = DEFAULT_BASE + offset + int(index) * width
            if values == sequence:
                absolute.append((address, values))
            elif all(
                values[i] - values[0] == sequence[i] - sequence[0]
                for i in range(1, len(values))
            ):
                relative.append((address, values))

    for title, found in (("Absolute", absolute), ("Relative", relative)):
        if not found:
            continue
        # One address matching as u8, u16 and u32 is a single finding, not
        # three: the wider reads only agree because the neighbouring bytes
        # happen to be zero. Report each address once.
        unique: dict[int, list[int]] = {}
        for address, values in found:
            unique.setdefault(address, values)
        ordered = sorted(unique.items())
        print(f"{title} matches: {len(ordered)} unique address(es)")
        for address, values in ordered[:limit]:
            print(f"    0x{address:08X}  values: {values}")
        if len(ordered) > limit:
            print(f"    ... and {len(ordered) - limit} more")
        print()

    if not absolute and not relative:
        print("No address followed that sequence.")
        print("Either a snapshot was taken on the wrong option -- check the")
        print("saved screenshots -- or the cursor is not stored as a plain")
        print("counter at these widths.")
    return 0


# The menu label sits in a band across the middle of the game viewport. These
# fractions deliberately exclude the pulsing up and down arrows above and below
# it: those animate on their own, and including them would make two frames
# showing the same option look different.
LABEL_BOX = (0.34, 0.72, 0.66, 0.82)

# Mean absolute grey difference, 0-255. Frames showing the same option differ
# only by video noise and land near zero; a different word is far above this.
LABEL_MATCH_TOLERANCE = 4.0


def _label_crop(image):
    """Return the menu label region, located relative to the game viewport."""
    from bt2 import vision

    viewport = vision.game_viewport(image)
    if viewport is None:
        viewport = (0, 0, image.width, image.height)
    left, top, right, bottom = viewport
    width = right - left
    height = bottom - top
    box = (
        int(left + LABEL_BOX[0] * width),
        int(top + LABEL_BOX[1] * height),
        int(left + LABEL_BOX[2] * width),
        int(top + LABEL_BOX[3] * height),
    )
    return image.crop(box)


def _group_by_label(crops: list) -> list[int]:
    """Assign each frame a group number, one per distinct on-screen label.

    Grouping by pixels rather than by reading the words avoids OCR entirely,
    which matters because these labels are stylised artwork with outlines and
    gradients -- exactly what general text recognition handles worst.
    """
    signatures = [np.asarray(crop.convert("L"), dtype=np.float32) for crop in crops]
    groups: list[int] = []
    representatives: list[np.ndarray] = []
    for signature in signatures:
        for index, existing in enumerate(representatives):
            if existing.shape != signature.shape:
                continue
            if float(np.mean(np.abs(existing - signature))) <= LABEL_MATCH_TOLERANCE:
                groups.append(index)
                break
        else:
            representatives.append(signature)
            groups.append(len(representatives) - 1)
    return groups


def autoscan(
    samples: int = 8,
    interval: float = 4.0,
    voice_enabled: bool = True,
    lead: int = 5,
    cue: str = "Down",
) -> int:
    """Capture RAM and screen together, then correlate them without help.

    This exists because driving the search by hand does not survive contact
    with a menu that times out: every pause to confirm which option is showing
    is a pause the attract demo can interrupt.  Here the player simply moves the
    cursor whenever they like while sampling runs, and the screen itself records
    which option each snapshot belongs to.
    """
    STORE.mkdir(parents=True, exist_ok=True)
    from bt2 import vision
    from probe_voice import Voice

    blocks: list[bytes] = []
    crops = []

    voice = Voice(enabled=voice_enabled)
    voice.countdown(
        lead, f"Auto scan. {samples} samples. Switch to the game now."
    )

    client = PineClient(timeout=15.0)
    try:
        for index in range(samples):
            # Cue first, then leave a beat for the press to land before the
            # screen and RAM are captured together.
            voice.cue(cue)
            time.sleep(interval)
            image = vision.capture_game_window()
            chunks = []
            for chunk_address in range(DEFAULT_BASE, FULL_END, CHUNK_BYTES):
                chunk_size = min(CHUNK_BYTES, FULL_END - chunk_address)
                chunks.append(
                    client.read_aligned_range(
                        chunk_address, chunk_size, allow_large=True
                    )
                )
                time.sleep(CHUNK_PAUSE)
            block = b"".join(chunks)
            blocks.append(block)
            crops.append(_label_crop(image))
            # Persist both halves. Capturing costs the player a live session;
            # keeping only the screenshots would mean re-running the whole
            # capture every time the analysis needs adjusting.
            (STORE / f"auto{index}.bin").write_bytes(block)
            image.save(STORE / f"auto{index}.png")
            print(f"  sample {index} captured")
            # Progress occasionally rather than every sample: a count after
            # each press would talk over the next cue.
            if (index + 1) % 5 == 0 and index + 1 < samples:
                voice.cue(f"{index + 1} of {samples}")
    finally:
        client.close()
        voice.say("Capture finished. Analysing.")

    groups = _group_by_label(crops)
    print(f"\nScreen showed {len(set(groups))} distinct label(s) across "
          f"{samples} samples: {groups}")
    for group in sorted(set(groups)):
        first = groups.index(group)
        print(f"  group {group}: samples "
              f"{[i for i, g in enumerate(groups) if g == group]} "
              f"(see auto{first}.png)")

    # Drop anything seen only once. A menu option the player sat on appears in
    # several samples; a single odd frame is the attract demo cutting in, or a
    # label caught mid-transition. Correlating against those is what makes the
    # search demand that the cursor differ during a cut-scene, which finds
    # nothing.
    counts = {group: groups.count(group) for group in set(groups)}
    keep = [i for i, group in enumerate(groups) if counts[group] > 1]
    dropped = [i for i in range(len(groups)) if i not in keep]
    if dropped:
        print(f"\nIgnoring one-off samples {dropped} (demo or mid-transition).")

    kept_groups = [groups[i] for i in keep]
    if len(set(kept_groups)) < 2:
        print("\nFewer than two options were on screen often enough to compare.")
        voice.say("Only one option seen. Another run needed, pressing down more "
                  "often.")
        voice.close()
        return 1

    print()
    found = _correlate([blocks[i] for i in keep], kept_groups)

    # Say the outcome and the next action, so the player learns the result
    # without leaving the game to read a terminal.
    options = len(set(kept_groups))
    if not found:
        voice.say(f"{options} options seen, but no address matched. "
                  "Another run needed.")
    elif len(found) <= 8:
        voice.say(f"Found it. {len(found)} addresses across {options} options. "
                  "Nothing more needed.")
    else:
        voice.say(f"{len(found)} candidates across {options} options. "
                  "Another run would narrow it.")
    voice.close()
    return 0 if found else 1


SPOKEN_COUNTS = {1: "Down", 2: "Down twice", 3: "Down three times",
                 4: "Down four times"}


def _require_screen(client, name: str) -> bool:
    """Refuse to capture unless the named screen is actually showing.

    A capture session costs the player three minutes at the controls and
    cannot be redone from disk.  Landing on the wrong screen used to produce a
    capture that looked fine and analysed to nothing, with the mistake only
    discovered afterwards.  The screen markers already exist; checking one up
    front is nearly free.
    """
    from bt2.menus import SCREENS

    screen = next((s for s in SCREENS if s.name.lower() == name.lower()), None)
    if screen is None:
        known = ", ".join(s.name for s in SCREENS)
        print(f"No marker known for {name!r}. Known screens: {known}")
        print("A screen with no marker must have one found before its cursor.")
        return False
    marker = bytes(
        client.read8(screen.marker_address + offset)
        for offset in range(len(screen.marker))
    )
    if marker == screen.marker:
        return True
    print(f"{screen.name} is not showing: {screen.marker_address:#010x} "
          f"reads {marker!r}, expected {screen.marker!r}.")
    return False


def pressscan(
    samples: int = 18,
    interval: float = 2.0,
    lead: int = 25,
    seed: int = 20260906,
    screen: str = "Main Menu",
) -> int:
    """Drive the cursor on a varying, spoken schedule and find what follows it.

    Grouping frames by their pixels fails on animated screens: the main menu's
    clouds, characters and flavour text keep moving, so two captures of the same
    option differ as much as captures of different options.  Without that, the
    only record of where the cursor was is the schedule of presses itself.

    A uniform "press down once each time" schedule is useless for that, because
    it is periodic: every animation counter whose cycle divides the sample count
    matches it just as well as the cursor does, which buried the real address
    among tens of thousands of false ones.  Varying the number of presses gives
    a sequence nothing incidental reproduces.

    The option count is not assumed.  Each plausible menu size implies a
    different pattern of repeats, so every size is tried and the ones that
    actually fit are reported.
    """
    import random

    from probe_voice import Voice

    STORE.mkdir(parents=True, exist_ok=True)
    from bt2 import vision

    # A fixed seed keeps a run reproducible while still being non-periodic.
    rng = random.Random(seed)
    schedule = [rng.choice((1, 1, 2, 2, 3, 4)) for _ in range(samples)]

    voice = Voice()
    client = PineClient(timeout=15.0)

    # Check before the countdown, not after: telling the player they are on the
    # wrong screen is only useful while they still have time to move.
    voice.say(f"Press scan. Go to {screen} now, and stay there.")
    voice.countdown(lead, "")
    if not _require_screen(client, screen):
        voice.say(f"Wrong screen. Expected {screen}. Nothing captured.")
        voice.close()
        client.close()
        return 1
    voice.say("Screen confirmed. Starting.")

    blocks: list[bytes] = []
    try:
        for index, presses in enumerate(schedule):
            voice.cue(SPOKEN_COUNTS[presses])
            # More presses need more time, plus a beat for the slide to settle.
            time.sleep(interval + 0.55 * (presses - 1))
            chunks = []
            for chunk_address in range(DEFAULT_BASE, FULL_END, CHUNK_BYTES):
                chunk_size = min(CHUNK_BYTES, FULL_END - chunk_address)
                chunks.append(
                    client.read_aligned_range(
                        chunk_address, chunk_size, allow_large=True
                    )
                )
                time.sleep(CHUNK_PAUSE)
            block = b"".join(chunks)
            blocks.append(block)
            (STORE / f"press{index}.bin").write_bytes(block)
            vision.capture_game_window().save(STORE / f"press{index}.png")
            print(f"  sample {index}: after {presses} press(es)")
            if (index + 1) % 6 == 0 and index + 1 < samples:
                voice.cue(f"{index + 1} of {samples}")
    finally:
        client.close()
        voice.say("Capture finished. Analysing.")

    (STORE / "press_schedule.txt").write_text(
        ",".join(str(p) for p in schedule), encoding="utf-8"
    )
    print(f"\nSchedule: {schedule}\n")
    return _analyse_presses(blocks, schedule, voice)


def _analyse_presses(blocks, schedule, voice=None) -> int:
    """Try each plausible option count and report which fit the schedule."""
    # Where the cursor started is unknown, but only the pattern of repeats
    # matters, and that is unchanged by a constant offset.
    travelled = []
    total = 0
    for presses in schedule:
        total += presses
        travelled.append(total)

    results = []
    for size in range(3, 17):
        groups = [step % size for step in travelled]
        if len(set(groups)) < 2:
            continue
        found = _correlate(blocks, groups, quiet=True)
        results.append((size, len(found), found))
        print(f"  {size:2d} options -> {len(found)} matching address(es)")

    plausible = [r for r in results if 0 < r[1] <= 40]
    if not plausible:
        print("\nNo option count produced a clean match.")
        if voice:
            voice.say("No match. Another run needed.")
            voice.close()
        return 1

    print()
    for size, count, found in plausible:
        print(f"=== {size} options: {count} address(es) ===")
        for address, values in sorted(found.items())[:12]:
            print(f"    0x{address:08X}  values: {values}")
        print()

    best = min(plausible, key=lambda r: r[1])
    if voice:
        voice.say(f"Found it. {best[0]} options, {best[1]} addresses.")
        voice.close()
    return 0


# The highlighted option on the main menu, centred and enlarged. Relative to
# the game viewport so it survives a resized window.
MAIN_MENU_LABEL = (0.14, 0.33, 0.72, 0.44)


def labels(
    address: int,
    lead: int = 30,
    box: tuple = MAIN_MENU_LABEL,
    expected: int = 10,
) -> int:
    """Collect one picture of the label for each value a cursor address takes.

    Reading the index is only half of an announcement: something has to say
    which words that index stands for, and the game has no string to supply
    them.  This walks the menu and keeps a picture of each option, so the
    spoken table can be written from what was actually on screen.

    A value is only trusted once it has held still across a screen capture,
    since a read taken mid-slide would pair an index with the previous label.
    """
    from PIL import Image

    from bt2 import vision
    from probe_voice import Voice

    STORE.mkdir(parents=True, exist_ok=True)
    voice = Voice()
    voice.countdown(
        lead, f"Label sweep. Press down when told, {expected} times."
    )

    seen: dict[int, Image.Image] = {}
    client = PineClient(timeout=15.0)
    try:
        # Cue each press rather than waiting to notice one. Passively watching
        # asks the player to guess when to act, and a player who cannot see the
        # screen has nothing to guess from.
        for _ in range(expected + 4):
            if len(seen) >= expected:
                break
            voice.cue("Down")
            time.sleep(1.7)
            before = client.read8(address)
            image = vision.capture_game_window()
            if client.read8(address) != before:
                continue  # Caught mid-slide; the next cue will come round again.
            if before in seen:
                continue
            left, top, right, bottom = vision.game_viewport(image) or (
                0, 0, image.width, image.height
            )
            width, height = right - left, bottom - top
            seen[before] = image.crop((
                int(left + box[0] * width), int(top + box[1] * height),
                int(left + box[2] * width), int(top + box[3] * height),
            ))
            print(f"  captured option {before} ({len(seen)}/{expected})")
    finally:
        client.close()

    if not seen:
        voice.say("Nothing captured.")
        voice.close()
        return 1

    # One tall image beats ten separate files: the table has to be written by
    # reading them side by side anyway, in index order.
    ordered = [seen[key] for key in sorted(seen)]
    sheet = Image.new(
        "RGB",
        (max(c.width for c in ordered), sum(c.height for c in ordered)),
        (0, 0, 0),
    )
    offset = 0
    for crop in ordered:
        sheet.paste(crop, (0, offset))
        offset += crop.height
    sheet.save(STORE / "label_sheet.png")

    missing = [v for v in range(expected) if v not in seen]
    print(f"\nCaptured options {sorted(seen)} into label_sheet.png")
    if missing:
        print(f"Missing: {missing}")
        voice.say(f"{len(seen)} of {expected} captured. Missing "
                  f"{len(missing)}.")
    else:
        voice.say(f"All {expected} options captured.")
    voice.close()
    return 0


def recorrelate() -> int:
    """Re-analyse the last autoscan from disk, without capturing again."""
    from PIL import Image

    saved = sorted(STORE.glob("auto*.bin"))
    if not saved:
        print("FAILED: no saved autoscan. Run: autoscan")
        return 1
    indices = [int(path.stem.removeprefix("auto")) for path in saved]
    blocks = [path.read_bytes() for path in saved]
    crops = [_label_crop(Image.open(STORE / f"auto{i}.png")) for i in indices]

    groups = _group_by_label(crops)
    print(f"Re-analysing {len(blocks)} saved samples: {groups}")
    counts = {group: groups.count(group) for group in set(groups)}
    keep = [i for i, group in enumerate(groups) if counts[group] > 1]
    dropped = [indices[i] for i in range(len(groups)) if i not in keep]
    if dropped:
        print(f"Ignoring one-off samples {dropped}.")
    kept_groups = [groups[i] for i in keep]
    if len(set(kept_groups)) < 2:
        print("Fewer than two options appear often enough to compare.")
        return 1
    print()
    return 0 if _correlate([blocks[i] for i in keep], kept_groups) else 1


def _correlate(
    blocks: list[bytes], groups: list[int], limit: int = 30, quiet: bool = False
) -> dict[int, list[int]]:
    """Report addresses that are constant per group and differ between groups.

    Returns the matches so a caller can summarise them aloud.
    """
    interpretations = [_views(block) for block in blocks]
    widths = {"u8": 1, "u16": 2, "u32": 4}
    found: dict[int, list[int]] = {}

    for position, (label, offset, first) in enumerate(interpretations[0]):
        others = [other[position][2] for other in interpretations[1:]]
        candidates = np.ones(len(first), dtype=bool)
        for other, group in zip(others, groups[1:]):
            if group == groups[0]:
                candidates &= other == first
            else:
                candidates &= other != first
        for index in np.flatnonzero(candidates):
            values = [int(first[index])] + [int(o[index]) for o in others]
            # The pairwise test above only compared against the first sample.
            # Require the full rule: identical wherever the screen was
            # identical, different wherever it differed.
            if any(
                (values[i] == values[j]) != (groups[i] == groups[j])
                for i in range(len(values))
                for j in range(i + 1, len(values))
            ):
                continue
            found.setdefault(
                DEFAULT_BASE + offset + int(index) * widths[label], values
            )

    if quiet:
        return found

    if not found:
        print("No address tracked the on-screen label.")
        return found

    print(f"Addresses tracking the label: {len(found)}")
    for address, values in sorted(found.items())[:limit]:
        print(f"    0x{address:08X}  values: {values}")
    if len(found) > limit:
        print(f"    ... and {len(found) - limit} more")
    return found


def watch(addresses: list[int], seconds: float = 20.0, period: float = 0.1) -> int:
    """Poll candidate addresses live while the cursor is moved by hand.

    A snapshot search can only prove that an address matched on the few frames
    that were captured.  Watching separates the real cursor from coincidence:
    the true one holds a steady value between presses, changes exactly when a
    button is pressed, and never leaves the range of valid options.  Noise that
    survived the search flickers on its own or wanders outside that range.
    """
    client = PineClient(timeout=15.0)
    history: dict[int, list[int]] = {address: [] for address in addresses}
    samples = 0
    try:
        print(f"Watching {len(addresses)} address(es) for {seconds:.0f}s. "
              "Move the cursor now.\n")
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            for address in addresses:
                value = client.read8(address)
                track = history[address]
                if not track or track[-1] != value:
                    track.append(value)
            samples += 1
            time.sleep(period)
    except KeyboardInterrupt:
        print("(stopped early)\n")
    finally:
        client.close()

    print(f"Took {samples} samples.\n")
    for address in addresses:
        track = history[address]
        distinct = sorted(set(track))
        summary = " -> ".join(str(v) for v in track[:24])
        if len(track) > 24:
            summary += " ..."
        print(f"0x{address:08X}  {len(track) - 1} change(s), values seen "
              f"{distinct}")
        print(f"    {summary}")
    return 0


class _Quiet:
    """A speaker that records instead of speaking, for diagnostics."""

    def __init__(self):
        self.said: list[str] = []

    def say(self, text, **_):
        self.said.append(text)

    def silence(self):
        pass

    def close(self):
        pass


def keys(seconds: float = 16.0) -> int:
    """Measure whether hotkeys are actually reaching the guide.

    "The key works sometimes" was diagnosed twice by reasoning and twice
    wrongly. It has three possible causes and this separates them: the press
    never reaches the process, the game does not have focus so the press is
    refused on purpose, or the loop looks too rarely to see it.
    """
    import collections
    import ctypes

    import win32gui

    from probe_voice import Voice
    from bt2.hotkeys import KeyWatcher
    from bt2.windows import focus_game_window, game_has_focus, game_windows

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    print(f"game_windows() -> {len(game_windows())} render candidate(s)")
    if not focus_game_window():
        print("Could not bring the game to the front. Switch to it yourself,")
        print("then run this again -- presses are refused without focus.")
        return 1

    watcher = KeyWatcher([0x47])
    voice = Voice()
    voice.say("Key check. Go to the game. I will ask you to press G three times.")
    voice.countdown(15, "")
    seen = 0
    focus = collections.Counter()
    titles = collections.Counter()
    try:
        for label, span in (("Press G now", 4), ("Again", 4),
                            ("One more time", 4), ("Stop", 3)):
            voice.cue(label)
            end = time.time() + span
            while time.time() < end:
                handle = win32gui.GetForegroundWindow()
                titles[win32gui.GetWindowText(handle)[:40]] += 1
                focus[game_has_focus()] += 1
                seen += watcher.take(0x47)
                time.sleep(0.05)
    finally:
        watcher.close()
        voice.say("Done.")
        voice.close()

    print(f"\npresses seen by the watcher: {seen} (three were asked for)")
    print(f"game had focus: {dict(focus)}")
    for title, count in titles.most_common(3):
        print(f"  {count:4d} samples in {title!r}")
    if seen == 0:
        print("\nNothing reached the process at all: the key is being taken "
              "before it gets here.")
    elif not focus.get(True):
        print("\nPresses arrive but the game never had focus, so they are "
              "refused on purpose.")
    else:
        print("\nPresses arrive and the game has focus, so anything still "
              "missing is the guide loop, not the keyboard.")
    return 0


def check() -> int:
    """Say what the mod thinks it is looking at, and why.

    Written after two faults that were invisible from the outside: a screen
    that announced nothing because the HUD heuristic called it gameplay, and a
    screen that announced the wrong name because another screen's marker
    matched first.  Both took minutes to find and would have taken seconds
    with this.  Run it whenever a screen is silent or wrong.
    """
    from bt2 import vision
    from bt2.menus import SCREENS, MenuReader

    client = PineClient(timeout=10.0)
    try:
        print("marker matches, in the order detection considers them:")
        for screen in SCREENS:
            try:
                hit = "MATCH" if screen.present(client) else "."
            except Exception as error:
                hit = f"error: {error}"
            note = "  (raw signature, weak)" if screen.weak_marker else ""
            note += "  (flagged as inside Adventure)" if screen.in_adventure else ""
            print(f"  {screen.name:<16} {hit}{note}")

        reader = MenuReader(_Quiet())
        found = reader._detect(client)
        print(f"\ndetected: {found.name if found else 'none -- would say Unknown screen'}")
        if found is not None and found.readable:
            raw, label, settled = found.option(client)
            print(f"cursor:   raw {raw} -> {label!r}" +
                  ("" if settled else "   MIRRORS DISAGREE, would stay silent"))
            if found.mirror is not None:
                print(f"mirror:   {client.read8(found.mirror)} "
                      f"at 0x{found.mirror:08X} (stride {found.mirror_stride})")
        elif found is not None:
            print("cursor:   not mapped for this screen; it names itself only")

        image = vision.capture_game_window()
        hud = vision.has_dragon_adventure_hud(image)
        print(f"\nAdventure HUD detector says gameplay: {hud}")
        if hud:
            if found is None:
                print("  Nothing recognised, so guidance runs. Expected during play.")
            elif not found.in_adventure:
                print(f"  {found.name} is up but is not flagged as living inside")
                print("  Adventure, so menu reading would be SUSPENDED and the")
                print("  screen would be silent. Set in_adventure=True on it.")
            else:
                print(f"  {found.name} is flagged, so its marker overrules this.")
    finally:
        client.close()
    return 0


def positionscan(screen_name: str, cues: list[str], lead: int = 20,
                 settle: float = 4.0) -> int:
    """Capture RAM and screen after each cued key press.

    The press scan assumes a menu that wraps and answers to one repeated key.
    The Game Level chooser is horizontal, has three entries, and is reached
    only from inside a story event, so a schedule of "down N times" says
    nothing about it.  Here each press is named instead, and every capture is
    paired with a screenshot so the position can be **read back afterwards**
    rather than assumed -- one missed press would otherwise poison the whole
    correlation while looking fine.
    """
    from probe_voice import Voice
    from bt2 import vision
    from bt2.menus import SCREENS

    screen = next((s for s in SCREENS if s.name.lower() == screen_name.lower()),
                  None)
    if screen is None:
        print(f"No marker known for {screen_name!r}.")
        return 1

    STORE.mkdir(parents=True, exist_ok=True)
    client = PineClient(timeout=15.0)
    voice = Voice()
    kept = 0
    try:
        voice.say(f"Position scan. Go to {screen_name} and rest your hands. "
                  f"Press only the keys I name. Starting in {lead} seconds.")
        voice.countdown(lead, "")
        if not _require_screen(client, screen_name):
            voice.say(f"Wrong screen. Expected {screen_name}. Nothing captured.")
            return 1
        voice.say("Confirmed. Here we go.")
        time.sleep(1.0)
        for index, cue in enumerate(cues):
            voice.cue(f"{cue} once")
            time.sleep(settle)
            if not screen.present(client):
                voice.say("Screen changed. Stopping.")
                break
            vision.capture_game_window().save(STORE / f"posn{index}.png")
            chunks = []
            for address in range(DEFAULT_BASE, FULL_END, CHUNK_BYTES):
                size = min(CHUNK_BYTES, FULL_END - address)
                chunks.append(client.read_aligned_range(address, size,
                                                        allow_large=True))
                time.sleep(CHUNK_PAUSE)
            (STORE / f"posn{index}.bin").write_bytes(b"".join(chunks))
            kept += 1
            print(f"  posn{index}: after {cue}")
        voice.say("Capture finished.")
    finally:
        client.close()
        voice.close()
    (STORE / "posn_cues.txt").write_text(",".join(cues[:kept]), encoding="utf-8")
    print(f"\n{kept} captures in {STORE}.")
    print("Read each posn*.png to see which entry is highlighted, then:")
    print("    python menu_probe.py fit 2,1,2,3,2,1")
    return 0


def fit(positions: list[int], prefix: str = "posn", limit: int = 16) -> int:
    """Find addresses that behave like an index across captures at known positions.

    Constant wherever the position is the same, different wherever it differs,
    and small enough to be an index.  That last constraint is what makes this
    usable: on Options it cut 39,101 raw matches to 67, and only five of those
    were an actual ramp.

    Positions are the ones **read off the screenshots**, not the ones intended.
    """
    saved = [STORE / f"{prefix}{i}.bin" for i in range(len(positions))]
    missing = [p.name for p in saved if not p.exists()]
    if missing:
        print(f"FAILED: no captures named {missing[0]} (and {len(missing)-1} more)")
        return 1
    groups = sorted(set(positions))
    if len(groups) < 2:
        print("FAILED: at least two different positions are needed.")
        return 1

    size = saved[0].stat().st_size
    chunk = 4 * 1024 * 1024
    survivors: dict[int, list[int]] = {}
    for start in range(0, size, chunk):
        count = min(chunk, size - start)
        stack = np.empty((len(saved), count), dtype=np.uint8)
        for index, path in enumerate(saved):
            with open(path, "rb") as handle:
                handle.seek(start)
                stack[index] = np.frombuffer(handle.read(count), dtype=np.uint8)
        ok = np.ones(count, dtype=bool)
        value = {}
        for group in groups:
            rows = stack[[i for i, p in enumerate(positions) if p == group]]
            ok &= (rows == rows[0]).all(axis=0)
            value[group] = rows[0]
        if not ok.any():
            continue
        for first in range(len(groups)):
            for second in range(first + 1, len(groups)):
                ok &= value[groups[first]] != value[groups[second]]
        if not ok.any():
            continue
        where = np.nonzero(ok)[0]
        values = np.stack([value[g][where] for g in groups], axis=1)
        small = values.max(axis=1) <= limit
        for offset, row in zip(where[small], values[small]):
            survivors[DEFAULT_BASE + start + int(offset)] = row.tolist()

    def ramp(values):
        # Strides seen so far: 1 on the main menu and Options, 2 on the title
        # screen, 4 on Game Level. Stride is per-screen and never assumed.
        for stride in (1, 2, 4):
            for base in range(0, limit):
                if values == [base + stride * k for k in range(len(groups))]:
                    return stride, base
        return None

    clean = {a: (v, ramp(v)) for a, v in survivors.items() if ramp(v)}
    print(f"{len(survivors)} addresses survive; {len(clean)} are an index ramp\n")
    for address, (values, (stride, base)) in sorted(clean.items()):
        print(f"  0x{address:08X}  {values}   stride {stride}, "
              f"position {groups[0]} = {base}")
    if not clean:
        print("None. Try more captures, or a position that was misread.")
        return 1
    print("\nAll of these fit the data they were found in, which proves nothing.")
    print("Verify on a transition they were not derived from before shipping.")
    return 0


def dryrun(seconds: float = 25.0) -> int:
    """Run the real guide loop with a recording speaker, and print what it says.

    The mod's whole output is speech, which makes it awkward to check and
    impossible to check without the player.  This drives the actual loop --
    not an imitation of it -- against the running game and writes down every
    line, so a change can be verified from a terminal.
    """
    import threading

    from bt2.guide import waiting_guide

    stop = threading.Event()
    speaker = _Quiet()
    original = speaker.say

    def echo(text, **kwargs):
        original(text, **kwargs)
        print(f"  SPOKE: {text}", flush=True)

    speaker.say = echo
    threading.Thread(target=lambda: (time.sleep(seconds), stop.set()),
                     daemon=True).start()
    print(f"Running the real guide loop for {seconds:.0f}s.\n")
    try:
        waiting_guide("objective", stop_event=stop, speaker=speaker)
    except Exception as error:
        print(f"  loop raised {type(error).__name__}: {error}")
    print(f"\n{len(speaker.said)} line(s) spoken.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    command = argv[1]
    if command == "snap":
        if len(argv) < 3:
            print("FAILED: give the snapshot a name, e.g. snap pos0")
            return 1
        end = FULL_END if "--full" in argv else DEFAULT_END
        return snap(argv[2], end)
    if command == "find":
        names = [a for a in argv[2:] if not a.startswith("-")]
        sequence = list(range(len(names)))
        for argument in argv[2:]:
            if argument.startswith("--sequence="):
                try:
                    sequence = [int(v) for v in argument.split("=", 1)[1].split(",")]
                except ValueError:
                    print("FAILED: --sequence takes numbers, e.g. --sequence=0,1,0")
                    return 1
        return find(names, sequence)
    if command == "autoscan":
        samples, interval = 8, 4.0
        for argument in argv[2:]:
            if argument.startswith("--samples="):
                samples = int(argument.split("=", 1)[1])
            elif argument.startswith("--interval="):
                interval = float(argument.split("=", 1)[1])
        lead = 5
        cue = "Down"
        for argument in argv[2:]:
            if argument.startswith("--lead="):
                lead = int(argument.split("=", 1)[1])
            elif argument.startswith("--cue="):
                cue = argument.split("=", 1)[1]
        return autoscan(
            samples, interval, "--quiet" not in argv, lead, cue
        )
    if command == "pressscan":
        target = "Main Menu"
        samples, interval, lead = 18, 2.0, 25
        for argument in argv[2:]:
            if argument.startswith("--samples="):
                samples = int(argument.split("=", 1)[1])
            elif argument.startswith("--interval="):
                interval = float(argument.split("=", 1)[1])
            elif argument.startswith("--lead="):
                lead = int(argument.split("=", 1)[1])
            elif argument.startswith("--screen="):
                target = argument.split("=", 1)[1]
        return pressscan(samples, interval, lead, screen=target)
    if command == "labels":
        address = int(argv[2], 16) if len(argv) > 2 else 0xAA12A8
        lead, expected = 30, 10
        for argument in argv[3:]:
            if argument.startswith("--lead="):
                lead = int(argument.split("=", 1)[1])
            elif argument.startswith("--expected="):
                expected = int(argument.split("=", 1)[1])
        return labels(address, lead, expected=expected)
    if command == "check":
        return check()
    if command == "keys":
        return keys()
    if command == "dryrun":
        span = 25.0
        for argument in argv[2:]:
            if argument.startswith("--seconds="):
                span = float(argument.split("=", 1)[1])
        return dryrun(span)
    if command == "positionscan":
        target, cues, lead = "Main Menu", ["Left", "Right"], 20
        for argument in argv[2:]:
            if argument.startswith("--screen="):
                target = argument.split("=", 1)[1]
            elif argument.startswith("--cues="):
                cues = [c.strip() for c in argument.split("=", 1)[1].split(",")]
            elif argument.startswith("--lead="):
                lead = int(argument.split("=", 1)[1])
        return positionscan(target, cues, lead)
    if command == "fit":
        if len(argv) < 3:
            print("Usage: fit 2,1,2,3,2,1   (positions read off the screenshots)")
            return 1
        return fit([int(v) for v in argv[2].split(",")])
    if command == "recorrelate":
        return recorrelate()
    if command == "watch":
        addresses = [int(a, 16) for a in argv[2:] if not a.startswith("-")]
        if not addresses:
            print("FAILED: give addresses in hex, e.g. watch 533B40 AA1290")
            return 1
        seconds = 20.0
        for argument in argv[2:]:
            if argument.startswith("--seconds="):
                seconds = float(argument.split("=", 1)[1])
        return watch(addresses, seconds)
    print(f"Unknown command '{command}'. Use snap, find or watch.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
