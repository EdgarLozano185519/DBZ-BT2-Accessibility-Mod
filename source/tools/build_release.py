"""Stamp the release: check it is coherent, then record what it contains.

`SHA256SUMS.txt` went stale because nothing regenerated it.  By the time it was
looked at, 26 recorded hashes no longer matched, 48 recorded files were gone,
and `bt2/menus.py` -- the file that does all the menu reading -- had never been
in it at all.  A manifest nobody regenerates is worse than none, because it
fails verification for the wrong reason and teaches people to ignore it.

The check that matters most runs first: **is the worker actually built from the
sources beside it?**  Editing `bt2/*.py` changes nothing until the worker is
rebuilt, and a release shipped in that state looks fine and behaves like the
old code.  That happened during development and cost a confused debugging
session.

    python build_release.py --release=2026.09.06-r5
    python build_release.py --check          # verify, change nothing
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "SHA256SUMS.txt"
BUILD_INFO = ROOT / "BUILD-INFO.json"
WORKER = ROOT / "worker" / "guide-worker.exe"

ROOT_FILES = ["BUILD-INFO.json", "DBZ BT2 Guide.exe", "README.md",
              "THIRD-PARTY.txt"]
TREES = ["worker", "licenses", "source"]
PACKAGES = ["numpy", "scipy", "Pillow", "pywin32", "hidapi", "pyinstaller"]


def release_files() -> list[Path]:
    """Everything that ships, in a stable order.

    Byte-for-byte reproducibility is not the goal here; knowing what was in a
    given release is. Caches are excluded because they are rebuilt per machine
    and would differ for reasons that mean nothing.
    """
    found = [ROOT / name for name in ROOT_FILES]
    for tree in TREES:
        for path in sorted((ROOT / tree).rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            # Running from source writes the learned atlas into source/profiles
            # (a frozen build uses LOCALAPPDATA instead). That is the player's
            # own data, it can carry map names they chose, and it differs per
            # machine -- so it is never part of a release.
            if "profiles" in path.relative_to(ROOT).parts:
                continue
            found.append(path)
    return [p for p in found if p.is_file() and p != MANIFEST]


def stale_sources() -> list[str]:
    """Source files newer than the worker built from them."""
    if not WORKER.is_file():
        return ["worker/guide-worker.exe is missing entirely"]
    built = WORKER.stat().st_mtime
    runtime = list((ROOT / "source" / "tools" / "bt2").glob("*.py"))
    runtime += [ROOT / "source" / "tools" / "guide_host.py",
                ROOT / "source" / "tools" / "pine_client.py"]
    return [str(p.relative_to(ROOT)).replace("\\", "/")
            for p in runtime if p.is_file() and p.stat().st_mtime > built]


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()


def read_manifest() -> dict[str, str]:
    if not MANIFEST.is_file():
        return {}
    recorded = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if "  " in line:
            value, name = line.split("  ", 1)
            recorded[name.strip()] = value
    return recorded


def verify() -> int:
    recorded = read_manifest()
    if not recorded:
        print("No manifest to verify.")
        return 1
    changed, missing = [], []
    for name, want in recorded.items():
        path = ROOT / name
        if not path.is_file():
            missing.append(name)
        elif digest(path) != want:
            changed.append(name)
    present = {str(p.relative_to(ROOT)).replace("\\", "/") for p in release_files()}
    unrecorded = sorted(present - set(recorded))
    print(f"{len(recorded)} recorded: {len(changed)} changed, "
          f"{len(missing)} missing, {len(unrecorded)} present but unrecorded")
    for group, names in (("changed", changed), ("missing", missing),
                         ("unrecorded", unrecorded)):
        for name in names[:6]:
            print(f"  {group:<11} {name}")
        if len(names) > 6:
            print(f"  {group:<11} ... and {len(names) - 6} more")
    return 0 if not (changed or missing or unrecorded) else 1


def versions() -> dict[str, str]:
    found = {"Python": ".".join(str(part) for part in sys.version_info[:3])}
    for name in PACKAGES:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "absent"
    return found


def stamp(release: str) -> int:
    stale = stale_sources()
    if stale:
        print("REFUSING: the worker is older than the sources it is built from.")
        for name in stale:
            print(f"  newer than the worker: {name}")
        print("\nRebuild first:  powershell -File source/tools/build_worker.ps1")
        print("then copy dist/guide-worker over worker/.")
        return 1

    existing = json.loads(BUILD_INFO.read_text(encoding="utf-8"))
    existing["release"] = release
    existing["dependencies"] = {
        "Python": versions()["Python"],
        "NVDA controller client":
            existing.get("dependencies", {}).get("NVDA controller client", "unknown"),
        **{name: versions()[name] for name in PACKAGES},
    }
    BUILD_INFO.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    print(f"BUILD-INFO.json -> {release}")

    before = read_manifest()
    files = release_files()
    lines = []
    for path in files:
        name = str(path.relative_to(ROOT)).replace("\\", "/")
        lines.append(f"{digest(path)}  {name}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")

    after = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in lines}
    added = sorted(set(after) - set(before))
    dropped = sorted(set(before) - set(after))
    altered = sorted(n for n in set(after) & set(before) if after[n] != before[n])
    print(f"SHA256SUMS.txt  -> {len(after)} files "
          f"({len(added)} added, {len(dropped)} dropped, {len(altered)} changed)")
    for name in added[:8]:
        print(f"  added    {name}")
    for name in dropped[:8]:
        print(f"  dropped  {name}")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv[1:])
    if args.check or not args.release:
        return verify()
    return stamp(args.release)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
