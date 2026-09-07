"""Extract the game's story text from the disc, offline.

The menu labels are artwork and have to be authored by hand, but story text is
not: it is real UTF-16LE inside `TXT-US-*` files in `ZS2US_1.AFS`.  Pulling it
off the disc gives two things.

First, a way to *check* text before speaking it.  The mod reads prose straight
out of RAM at addresses recorded in one run, and a read that lands somewhere
wrong can still look like a sentence.  "Is this an actual line of game text" is
a far sharper question than "do these bytes look like words", and it can only be
asked against the real corpus.

Second, the groundwork for reading cutscene subtitles, where the corpus is what
makes the search tractable at all.  Each file is a scene: a table of text
boxes in the order the game shows them, so a box found in RAM identifies both
the scene and how far through it the game has got.

Nothing here writes into the repository: extracted text is game content and
stays in `reference/`, which is git-ignored.

    python extract_text.py                  # uses the desktop app's game path
    python extract_text.py --iso=PATH
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path

SECTOR = 2048
PVD_SECTOR = 16
STORE = Path(__file__).resolve().parents[2] / "reference" / "corpus"

# Every TXT-US file on this disc uses 5, 6, 10 or 30 slots; the cap only
# rejects a header that is not one of these files at all.
MAX_SLOTS = 64
BOM = b"\xff\xfe"

# Directory-record fields, by offset. Both-endian numbers are read little-end
# first, which is the half every player of this format agrees on.
_EXTENT = 2
_LENGTH = 10
_FLAGS = 25
_NAME_LEN = 32
_NAME = 33


class DiscError(RuntimeError):
    pass


def _records(block: bytes):
    """Walk the directory records packed into one directory extent."""
    offset = 0
    while offset < len(block):
        length = block[offset]
        if length == 0:
            # Records never straddle a sector; a zero means skip to the next.
            offset = (offset // SECTOR + 1) * SECTOR
            if offset >= len(block):
                return
            continue
        record = block[offset:offset + length]
        name_length = record[_NAME_LEN]
        name = bytes(record[_NAME:_NAME + name_length])
        yield {
            "name": name.split(b";")[0].decode("ascii", "replace"),
            "extent": struct.unpack_from("<I", record, _EXTENT)[0],
            "length": struct.unpack_from("<I", record, _LENGTH)[0],
            "directory": bool(record[_FLAGS] & 0x02),
        }
        offset += length


def walk(iso, extent: int, length: int, prefix: str = ""):
    """Yield every file on the disc, descending into directories.

    The archives live under DATA/, not in the root, so a root-only search finds
    nothing and says the disc is wrong when it is not.
    """
    iso.seek(extent * SECTOR)
    block = iso.read(length)
    for entry in _records(block):
        name = entry["name"]
        # The "." and ".." records, whose names are a single
        # control byte rather than text.
        if len(name) <= 1 and not name.isalnum():
            continue  # The "." and ".." records.
        path = f"{prefix}/{entry['name']}" if prefix else entry["name"]
        if entry["directory"]:
            yield from walk(iso, entry["extent"], entry["length"], path)
        else:
            yield path, entry["extent"] * SECTOR, entry["length"]


def find_on_disc(iso, wanted: str) -> tuple[int, int]:
    """Return the (byte offset, size) of a file anywhere on the disc."""
    iso.seek(PVD_SECTOR * SECTOR)
    pvd = iso.read(SECTOR)
    if pvd[1:6] != b"CD001":
        raise DiscError("Not an ISO9660 image: no CD001 at sector 16.")
    root = pvd[156:156 + 34]
    extent = struct.unpack_from("<I", root, _EXTENT)[0]
    length = struct.unpack_from("<I", root, _LENGTH)[0]
    for path, offset, size in walk(iso, extent, length):
        if path.upper().endswith(wanted.upper()):
            return offset, size
    raise DiscError(f"{wanted} is not on the disc.")


def afs_entries(iso, base: int) -> list[tuple[str, int, int]]:
    """Read an AFS table of contents as (name, absolute offset, size).

    AFS is a flat archive: a magic word, a count, then that many
    (offset, size) pairs, then one more pair pointing at a table of names.
    Names are optional in the format, so a nameless archive is not an error --
    the entries are simply reported by index.
    """
    iso.seek(base)
    header = iso.read(8)
    if header[:4] != b"AFS\x00":
        raise DiscError(f"No AFS magic at {base:#x}; found {header[:4]!r}.")
    count = struct.unpack_from("<I", header, 4)[0]
    if not 0 < count < 1_000_000:
        raise DiscError(f"Implausible AFS entry count {count}.")
    table = iso.read(count * 8 + 8)
    entries = []
    for index in range(count):
        offset, size = struct.unpack_from("<II", table, index * 8)
        entries.append([f"{index:04d}", base + offset, size])

    # The pair after the last entry points at the name directory: 32-byte
    # names followed by 16 bytes the game uses and we do not.
    name_offset, name_size = struct.unpack_from("<II", table, count * 8)
    if name_offset and name_size:
        iso.seek(base + name_offset)
        names = iso.read(name_size)
        for index in range(min(count, len(names) // 48)):
            raw = names[index * 48:index * 48 + 32]
            text = raw.split(b"\x00")[0].decode("ascii", "replace").strip()
            if text:
                entries[index][0] = text
    return [(n, o, s) for n, o, s in entries]


class TextFileError(ValueError):
    pass


def parse_text_file(data: bytes) -> list[str]:
    """Decode one TXT-US file into its text boxes, by slot.

    The format is self-describing rather than a soup of strings, which matters:
    a regex over printable ASCII silently split every line containing a
    typographic apostrophe and produced fragments that match nothing in RAM.

        u32   slot count
        u32   [count + 1] offsets, the last one marking the end
        ...   padding to an 8-byte boundary
        each slot: a UTF-16LE BOM, the text, a null terminator

    An unused slot is an empty range -- two equal offsets -- and is returned as
    an empty string so a slot's index is also its position in this list.  Line
    breaks inside a box are real: they are where the game wraps its text box,
    and they are kept so a caller can decide whether to speak them.
    """
    if len(data) < 8:
        raise TextFileError("shorter than a header")
    count = struct.unpack_from("<I", data, 0)[0]
    if not 0 < count <= MAX_SLOTS:
        raise TextFileError(f"implausible slot count {count}")
    first = 4 + (count + 1) * 4
    first += -first % 8
    if len(data) < first:
        raise TextFileError("truncated offset table")
    offsets = struct.unpack_from(f"<{count + 1}I", data, 4)
    if offsets[0] != first:
        raise TextFileError(f"first offset {offsets[0]:#x}, expected {first:#x}")
    if list(offsets) != sorted(offsets):
        raise TextFileError("offsets are not ascending")
    if offsets[-1] > len(data):
        raise TextFileError("offsets run past the end of the file")

    boxes = []
    for index in range(count):
        blob = data[offsets[index]:offsets[index + 1]]
        if not blob:
            boxes.append("")
            continue
        if blob[:2] != BOM:
            raise TextFileError(f"slot {index} does not start with a BOM")
        boxes.append(decode_box(blob[2:]))
    return boxes


def decode_box(raw: bytes) -> str:
    """Decode one null-terminated UTF-16LE box, BOM already removed."""
    end = raw.find(b"\x00\x00")
    if end < 0:
        end = len(raw)
    if end % 2:
        end += 1
    return raw[:end].decode("utf-16-le", "replace")


def spoken(box: str) -> str:
    """Collapse a box's text-box line breaks into one spoken line."""
    return " ".join(box.split())


def extract(iso_path: Path) -> int:
    STORE.mkdir(parents=True, exist_ok=True)
    with open(iso_path, "rb") as iso:
        base, size = find_on_disc(iso, "ZS2US_1.AFS")
        print(f"ZS2US_1.AFS at {base:#x}, {size / 1e6:.1f} MB")
        entries = afs_entries(iso, base)
        print(f"{len(entries)} files in the archive")

        wanted = [e for e in entries if e[0].upper().startswith("TXT-US")]
        print(f"{len(wanted)} of them are TXT-US-*")
        if not wanted:
            named = sum(1 for n, _, _ in entries if not n.isdigit())
            print("No TXT-US files found."
                  + ("" if named else " The archive carries no names, so files"
                     " must be identified by content instead."))

        # Names in this archive are not unique -- 553 TXT-US entries share 81
        # names between them -- so the offset goes in the key. Keying on the
        # name alone silently kept one file in seven and looked like it had
        # worked.
        corpus: dict[str, list[str]] = {}
        refused = []
        for name, offset, length in wanted:
            iso.seek(offset)
            try:
                corpus[f"{name}@{offset:#x}"] = parse_text_file(iso.read(length))
            except TextFileError as error:
                refused.append((name, offset, str(error)))

    # A file this parser cannot read is reported rather than skipped quietly.
    # Every one of the 553 on this disc parses; a refusal means the format
    # assumption has met something it does not cover, and the corpus is short
    # by however many lines that file held.
    if refused:
        print(f"\n{len(refused)} file(s) did not parse:")
        for name, offset, why in refused[:10]:
            print(f"    {name}@{offset:#x}: {why}")

    boxes = [box for group in corpus.values() for box in group if box]
    lines = sorted({spoken(box) for box in boxes})
    (STORE / "story_scenes.json").write_text(
        json.dumps(corpus, indent=1, ensure_ascii=False), encoding="utf-8")
    (STORE / "story_lines.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(corpus)} files, {len(boxes)} text boxes, "
          f"{len(lines)} distinct lines -> {STORE}")
    for line in lines[:8]:
        print(f"    {line[:88]}")
    return 0


def stored_game_path() -> Path | None:
    """The game dump the desktop app was last pointed at.

    This used to ask ``bt2.profiles`` for it, which never worked: that store
    holds map and area profiles and has no ``get``, so running without --iso
    always raised.  The desktop app is what actually knows the path, and it
    writes it beside its own settings.
    """
    for root in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "DBZ BT2 Guide",
        Path(__file__).resolve().parents[2],
    ):
        settings = root / "desktop-settings.json"
        if not settings.is_file():
            continue
        try:
            stored = json.loads(settings.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        game = stored.get("game")
        if game:
            return Path(game)
    return None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", default=None)
    args = parser.parse_args(argv[1:])
    iso_path = Path(args.iso) if args.iso else stored_game_path()
    if not iso_path or not iso_path.is_file():
        print(f"No such ISO: {iso_path}\nPass --iso=PATH.")
        return 1
    try:
        return extract(iso_path)
    except DiscError as error:
        print(f"FAILED: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
