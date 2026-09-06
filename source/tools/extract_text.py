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
makes the search tractable at all.

Nothing here writes into the repository: extracted text is game content and
stays in `reference/`, which is git-ignored.

    python extract_text.py                  # uses the ISO from profiles
    python extract_text.py --iso=PATH
"""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from pathlib import Path

SECTOR = 2048
PVD_SECTOR = 16
STORE = Path(__file__).resolve().parents[2] / "reference" / "corpus"

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


def strings_in(block: bytes, minimum: int = 3) -> list[str]:
    """Pull null-terminated UTF-16LE runs of printable text out of a file."""
    found = []
    for match in re.finditer(rb"(?:[\x20-\x7e\x0a\x0d]\x00){%d,}" % minimum, block):
        text = match.group().decode("utf-16-le", "replace")
        text = " ".join(text.split())
        if text:
            found.append(text)
    return found


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
        for name, offset, length in wanted:
            iso.seek(offset)
            corpus[f"{name}@{offset:#x}"] = strings_in(iso.read(length))

    lines = sorted({line for group in corpus.values() for line in group})
    (STORE / "story_strings.json").write_text(
        json.dumps(corpus, indent=1, ensure_ascii=False), encoding="utf-8")
    (STORE / "story_lines.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n{len(lines)} distinct lines -> {STORE}")
    for line in lines[:8]:
        print(f"    {line[:88]}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", default=None)
    args = parser.parse_args(argv[1:])
    if args.iso:
        iso_path = Path(args.iso)
    else:
        from bt2.profiles import default_store
        stored = default_store().load()
        iso_path = Path(stored.get("iso", "")) if stored else Path("")
    if not iso_path.is_file():
        print(f"No such ISO: {iso_path}\nPass --iso=PATH.")
        return 1
    try:
        return extract(iso_path)
    except DiscError as error:
        print(f"FAILED: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
