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


def autoscan(samples: int = 8, interval: float = 4.0) -> int:
    """Capture RAM and screen together, then correlate them without help.

    This exists because driving the search by hand does not survive contact
    with a menu that times out: every pause to confirm which option is showing
    is a pause the attract demo can interrupt.  Here the player simply moves the
    cursor whenever they like while sampling runs, and the screen itself records
    which option each snapshot belongs to.
    """
    STORE.mkdir(parents=True, exist_ok=True)
    from bt2 import vision

    blocks: list[bytes] = []
    crops = []

    client = PineClient(timeout=15.0)
    try:
        for index in range(samples):
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
            if index < samples - 1:
                time.sleep(interval)
    finally:
        client.close()

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
        print("Re-run while pressing down steadily -- that also stops the")
        print("attract demo from starting.")
        return 1

    print()
    return _correlate([blocks[i] for i in keep], kept_groups)


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
    return _correlate([blocks[i] for i in keep], kept_groups)


def _correlate(blocks: list[bytes], groups: list[int], limit: int = 30) -> int:
    """Report addresses that are constant per group and differ between groups."""
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

    if not found:
        print("No address tracked the on-screen label.")
        return 1

    print(f"Addresses tracking the label: {len(found)}")
    for address, values in sorted(found.items())[:limit]:
        print(f"    0x{address:08X}  values: {values}")
    if len(found) > limit:
        print(f"    ... and {len(found) - limit} more")
    return 0


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
        return autoscan(samples, interval)
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
