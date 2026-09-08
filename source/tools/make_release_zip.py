"""Build the release zip: every file the manifest names, plus the manifest.

    python source/tools/make_release_zip.py

Writes `DBZ-BT2-Guide-<release>.zip` into the repository root, with everything
under a single top-level folder of the same name, so extracting it does not
spray files into whichever directory the player happened to be in.

It refuses to build from a folder that does not match its own manifest. The
zip is what gets attached to a GitHub release, and the manifest is the only
record of what a given release contained; a zip that disagrees with it would
be exactly the kind of artefact `build_release.py --check` exists to catch.
Stamp first, then zip.

Zips are git-ignored on purpose. The release lives on GitHub's release page,
the source history does not carry 170 MB bundles, and the two stay separate.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_release  # noqa: E402

ROOT = build_release.ROOT
MANIFEST = build_release.MANIFEST


def main() -> int:
    release = json.loads(build_release.BUILD_INFO.read_text(encoding="utf-8"))["release"]
    stale = build_release.stale_sources()
    if stale:
        print("REFUSING: the worker is older than its sources; rebuild and stamp first.")
        return 1

    recorded = build_release.read_manifest()
    if not recorded:
        print("REFUSING: no SHA256SUMS.txt; stamp the release first.")
        return 1
    files = build_release.release_files()
    problems = []
    for path in files:
        name = str(path.relative_to(ROOT)).replace("\\", "/")
        digest = build_release.digest(path)
        if name not in recorded:
            problems.append(f"not in manifest: {name}")
        elif recorded[name] != digest:
            problems.append(f"changed since stamping: {name}")
    present = {str(p.relative_to(ROOT)).replace("\\", "/") for p in files}
    for name in recorded:
        if name not in present:
            problems.append(f"in manifest but missing: {name}")
    if problems:
        print("REFUSING: the folder does not match SHA256SUMS.txt.")
        for line in problems[:12]:
            print(f"  {line}")
        print("Run build_release.py --release=... and try again.")
        return 1

    folder = f"DBZ-BT2-Guide-{release}"
    target = ROOT / f"{folder}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in files + [MANIFEST]:
            bundle.write(path, f"{folder}/{path.relative_to(ROOT).as_posix()}")
    size = target.stat().st_size / (1024 * 1024)
    print(f"{target.name}: {len(files) + 1} files, {size:.1f} MB, verified against the manifest.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
