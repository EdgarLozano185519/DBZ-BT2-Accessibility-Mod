"""Find where the game keeps the story text it is currently showing.

The menus were found by hunting a cursor: a small number that steps by one when
a button is pressed.  Story text has no cursor -- a cutscene advances on its
own -- so the search here is the other way round.  Every line the game can show
is known offline, extracted from the disc by `extract_text.py`, so the question
is not "did these bytes change" but "are these bytes a line of this game's
dialogue".  That is enormously more selective: frame noise changes constantly
and never spells a sentence.

Text is stored the same way in RAM as on the disc: a UTF-16LE byte order mark,
the text, a null terminator.  The BOM is what makes a scan cheap -- there are
only so many `ff fe` pairs in 31 MB, and each one either decodes to a known
line or does not.

    python story_probe.py follow               # speak prose as it is displayed
    python story_probe.py capture cut          # record RAM once per text box
    python story_probe.py scan diff0            # what story text is resident
    python story_probe.py compare a0 a1 a2      # what changed between captures
    python story_probe.py names                 # walk the event-name table
    python story_probe.py live                  # read the resident pool now

`compare` is the one that matters.  An address holding a *different* known line
in each capture is a display slot -- the thing worth reading.  An address
holding the *same* line every time is a resident block, and reading it would
report whatever was loaded rather than what is on screen.  That distinction is
the whole point: `0x00D1A782` was recorded as the Game Level event name when it
is really entry 0 of a table, and it announces the first event's name on every
event to this day.  It was derived from captures that could not tell the two
apart.

`capture` records the captures `compare` needs: it watches the screen and takes
RAM and a picture together every time the text box changes, so the player just
plays the cutscene and nothing has to be timed by hand. Menu captures still
come from `menu_probe.py snap`, which stops at 0x01000000 by default -- story
text has been seen above that, so those need `--full`.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from extract_text import BOM, decode_box, spoken

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "reference" / "probe"
CORPUS = ROOT / "reference" / "corpus" / "story_scenes.json"

# Captures start here; `menu_probe.py snap` reads from this address up.
CAPTURE_BASE = 0x00100000
# The cutscene text pool sits at 0x0109FB70 on this scene, above the 0x01000000
# that `snap` stops at by default -- so story captures must cover the full
# 31 MB or they miss the very thing they are for.
CAPTURE_END = 0x02000000
CHUNK = 1 << 20

# No text box on this disc is longer than 156 characters, so a run that never
# terminates within this many bytes is not one of them.
MAX_BOX_BYTES = 400


def load_corpus() -> dict[str, tuple[str, int]]:
    """Every text box on the disc, keyed by its spoken form.

    The value says which scene file it belongs to and which slot within it, so
    a hit in RAM says not just "this is game text" but "this is scene X, box
    N" -- which is how far through the scene the game has got.
    """
    if not CORPUS.is_file():
        raise SystemExit(
            f"No corpus at {CORPUS}.\nRun: python extract_text.py"
        )
    scenes = json.loads(CORPUS.read_text(encoding="utf-8"))
    corpus: dict[str, tuple[str, int]] = {}
    for scene, boxes in scenes.items():
        for index, box in enumerate(boxes):
            if box:
                corpus.setdefault(spoken(box), (scene, index))
    return corpus


def boxes_in(data: bytes, base: int = CAPTURE_BASE):
    """Yield (address, text) for every BOM-prefixed readable box in a block."""
    position = 0
    while True:
        position = data.find(BOM, position)
        if position < 0:
            return
        text = decode_box(data[position + 2:position + 2 + MAX_BOX_BYTES])
        if text:
            yield base + position, spoken(text)
        position += 2


def _hits(data: bytes, corpus) -> dict[int, tuple[str, str, int]]:
    found = {}
    for address, text in boxes_in(data):
        known = corpus.get(text)
        if known:
            found[address] = (text, known[0], known[1])
    return found


def _read(name: str) -> bytes:
    path = PROBE / f"{name}.bin"
    if not path.is_file():
        raise SystemExit(f"No capture at {path}.")
    return path.read_bytes()


def scan(name: str, limit: int = 30) -> int:
    corpus = load_corpus()
    found = _hits(_read(name), corpus)
    print(f"{name}: {len(found)} known story boxes resident\n")
    if not found:
        print("No story text in this capture. Outside a cutscene and outside\n"
              "Dragon Adventure that is the expected answer, not a failure.")
        return 0

    scenes = {}
    for address in sorted(found):
        text, scene, slot = found[address]
        scenes.setdefault(scene, []).append((address, slot, text))
    print(f"{len(scenes)} scene file(s) represented:")
    for scene, rows in list(scenes.items())[:limit]:
        span = f"0x{rows[0][0]:08X}-0x{rows[-1][0]:08X}"
        print(f"  {scene.split('@')[0]:18} {len(rows):2} boxes  {span}")
    print("\nfirst boxes, in address order:")
    for address in sorted(found)[:12]:
        text, scene, slot = found[address]
        print(f"  0x{address:08X} [{slot}] {scene.split('@')[0]:16} {text[:48]!r}")
    return 0


def compare(names: list[str]) -> int:
    """Sort the addresses holding story text into display slots and blocks.

    This is the test that separates the two possible answers.  A candidate that
    only ever holds one line proves nothing about what is on screen; it has to
    follow the dialogue to be worth reading.
    """
    corpus = load_corpus()
    per_capture = [(name, _hits(_read(name), corpus)) for name in names]
    for name, found in per_capture:
        print(f"{name}: {len(found)} known boxes")

    everywhere = set(per_capture[0][1])
    for _, found in per_capture[1:]:
        everywhere &= set(found)
    print(f"\naddresses holding story text in all {len(names)} captures: "
          f"{len(everywhere)}")

    changing, steady = [], 0
    for address in sorted(everywhere):
        texts = [found[address][0] for _, found in per_capture]
        if len(set(texts)) > 1:
            changing.append((address, texts))
        else:
            steady += 1
    print(f"  same line every time (resident block): {steady}")
    print(f"  a different line each time (display slot): {len(changing)}")

    if not changing:
        print("\nNothing followed the dialogue. Either the captures were taken\n"
              "on the same line, or the game renders by index into the block --\n"
              "in which case the index is what to hunt, not an address.")
        return 0

    print("\nCandidates, best first:")
    for address, texts in changing[:20]:
        print(f"  0x{address:08X}")
        for name, text in zip(names, texts):
            print(f"      {name:10} {text[:60]!r}")
    return 0


# The reader itself lives in the shipped module, so this tool and the mod can
# never disagree about what counts as readable text.
from bt2.story import DISPLAY_POINTER, StoryReader, read_displayed  # noqa: E402


def follow(seconds: float = 180.0, voice: bool = True) -> int:
    """Speak each line of prose as the game displays it.

    This is the shipped reader, driven from the terminal: the same
    `bt2.story.StoryReader` the mod uses, so what is heard here is what the mod
    would say.
    """
    from pine_client import PineClient
    from probe_voice import Voice

    speaker = Voice(enabled=voice)
    reader = StoryReader(speaker)
    client = PineClient(timeout=20.0)
    seen = 0
    deadline = time.monotonic() + seconds
    try:
        speaker.say("Following the story text.")
        while time.monotonic() < deadline:
            if reader.poll(client) is not None:
                seen += 1
            time.sleep(0.15)
    except KeyboardInterrupt:
        print("(stopped)")
    finally:
        client.close()
    print(f"\n{seen} line(s) read.")
    return 0


def capture(prefix: str = "cut", boxes: int = 8, seconds: float = 180.0,
            voice: bool = True) -> int:
    """Capture RAM once per text box while the player advances a cutscene.

    A cutscene has no cursor, so the earlier plan was to pause the emulator and
    coordinate each capture by hand.  Neither turns out to be necessary.  A
    text box waits for a button press -- the scene region was byte-identical
    over fifteen seconds -- so nothing runs away, and a full 31 MB read takes
    0.6 seconds, not the ten the subtitle-search note implied.

    So the player just plays.  This watches the screen, and every time the text
    box changes it records RAM and the picture together.  The picture is what
    says which box was showing, so nobody has to see the screen to label the
    captures afterwards.

    A capture is kept only if the screen still shows the same box after the
    read finished.  A press landing mid-read would otherwise pair one box's
    picture with another box's memory, which is exactly the kind of quietly
    wrong evidence this project has been bitten by.
    """
    import numpy as np
    from bt2 import vision
    from pine_client import PineClient
    from probe_voice import Voice

    def text_region(image):
        """The dialogue box area, as a small greyscale array."""
        width, height = image.size
        crop = image.convert("L").crop(
            (int(width * 0.25), int(height * 0.60),
             int(width * 0.95), int(height * 0.94))
        ).resize((64, 32))
        return np.asarray(crop, dtype=np.int16)

    def changed(a, b, threshold=6.0) -> bool:
        return a is None or float(np.abs(a - b).mean()) > threshold

    speaker = Voice(enabled=voice)
    client = PineClient(timeout=30.0)
    PROBE.mkdir(parents=True, exist_ok=True)
    kept, last, deadline = 0, None, time.monotonic() + seconds
    try:
        if client.status() not in (0, 1):
            print("PCSX2 is not running a game.")
            return 1
        speaker.say("Capturing. Advance the cutscene at your own pace.")
        while kept < boxes and time.monotonic() < deadline:
            image = vision.capture_game_window()
            region = text_region(image)
            if not changed(last, region):
                time.sleep(0.25)
                continue
            time.sleep(0.35)                     # let the box finish drawing
            image = vision.capture_game_window()
            region = text_region(image)

            blocks = []
            for address in range(CAPTURE_BASE, CAPTURE_END, CHUNK):
                blocks.append(client.read_aligned_range(
                    address, CHUNK, allow_large=True))
            after = text_region(vision.capture_game_window())
            if changed(region, after):
                print("  (box changed mid-read, retrying)")
                continue

            name = f"{prefix}{kept}"
            (PROBE / f"{name}.bin").write_bytes(b"".join(blocks))
            image.save(PROBE / f"{name}.png")
            last = region
            kept += 1
            print(f"  captured {name}")
            speaker.say(str(kept))
        speaker.say(f"Done. {kept} captured.")
    except KeyboardInterrupt:
        print("(stopped early)")
    finally:
        client.close()
    print(f"\n{kept} capture(s) in {PROBE}")
    if kept:
        print(f"Next: python story_probe.py compare "
              + " ".join(f"{prefix}{i}" for i in range(kept)))
    return 0


NAME_TABLE_START = 0x00D1A782
NAME_TABLE_STRIDE = 0x40
NAME_TABLE_END = 0x00D1E3C0


def names(name: str = "diff0") -> int:
    """Walk the event-name table, honouring entries that span two granules.

    `docs/memory-map.md` records this table as regular, and the plan for
    fixing the F12 event name is `0x00D1A782 + 0x40 * n`.  It is not regular.
    A name longer than 31 characters fills its granule and runs into the next
    one, so from the first long name onwards the slot number and the event
    number drift apart -- and some slots are empty besides.  Indexing by
    arithmetic reads a continuation fragment ("n!", "pe Baby", "use") and
    speaks it with full confidence.

    Walking instead is exact: a slot with no null terminator inside it is
    continued by the slot after it.
    """
    data = _read(name)
    slots = (NAME_TABLE_END - NAME_TABLE_START) // NAME_TABLE_STRIDE

    def granule(index: int) -> tuple[str | None, bool]:
        offset = NAME_TABLE_START - CAPTURE_BASE + NAME_TABLE_STRIDE * index
        raw = data[offset:offset + NAME_TABLE_STRIDE]
        end = raw.find(b"\x00\x00")
        spilled = end < 0
        if spilled:
            end = len(raw)
        if end % 2:
            end += 1
        try:
            return raw[:end].decode("utf-16-le"), spilled
        except ValueError:
            return None, False

    entries, index = [], 0
    while index < slots:
        text, spilled = granule(index)
        if text is None:
            index += 1
            continue
        used = 1
        while spilled and index + used < slots:
            more, spilled = granule(index + used)
            if more is None:
                break
            text += more
            used += 1
        text = " ".join(text.split())
        if text:
            entries.append((index, used, text))
        index += used

    long = [e for e in entries if e[1] > 1]
    print(f"{slots} granules -> {len(entries)} entries, "
          f"{len(long)} of them spanning two")
    print("\nEntries whose name overflows its granule -- every event after the\n"
          "first of these is misnumbered by simple arithmetic:")
    for slot, used, text in long:
        print(f"  granule {slot:3} x{used}  {text!r}")
    print("\nFirst 12 entries, walked:")
    for slot, used, text in entries[:12]:
        print(f"  granule {slot:3} x{used}  {text!r}")
    return 0


def live() -> int:
    """Read whatever story text is resident right now, through PINE."""
    from pine_client import PineClient

    corpus = load_corpus()
    client = PineClient(timeout=15.0)
    try:
        if client.status() not in (0, 1):
            print("PCSX2 is not running a game.")
            return 1
        # The pool the Dragon Adventure screens keep resident. Read as one
        # range rather than byte at a time: 30 KB is a single request.
        start, end = 0x00D1A000, 0x00D25000
        size = end - start
        block = client.read_aligned_range(start, size + (-size % 8),
                                          allow_large=True)
    finally:
        client.close()

    found = {}
    for address, text in boxes_in(block, start):
        known = corpus.get(text)
        if known:
            found[address] = (text, known[0], known[1])
    print(f"{len(found)} known story boxes in 0x{start:08X}-0x{end:08X}")
    for address in sorted(found)[:20]:
        text, scene, slot = found[address]
        print(f"  0x{address:08X} [{slot}] {scene.split('@')[0]:16} {text[:48]!r}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    command = argv[1]
    if command == "scan":
        if len(argv) < 3:
            print("FAILED: name a capture, e.g. scan diff0")
            return 1
        return scan(argv[2])
    if command == "compare":
        if len(argv) < 4:
            print("FAILED: name at least two captures, e.g. compare a0 a1")
            return 1
        return compare(argv[2:])
    if command == "follow":
        return follow(voice="--quiet" not in argv)
    if command == "capture":
        prefix = argv[2] if len(argv) > 2 and not argv[2].startswith("-") else "cut"
        boxes = 8
        for argument in argv[2:]:
            if argument.startswith("--boxes="):
                boxes = int(argument.split("=", 1)[1])
        return capture(prefix, boxes, voice="--quiet" not in argv)
    if command == "names":
        return names(argv[2] if len(argv) > 2 else "diff0")
    if command == "live":
        return live()
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
