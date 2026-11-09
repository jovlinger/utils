#!/usr/bin/env python3
"""Dry-run: print which album dirs under FILES would be renamed by ingest_rename.

Usage (after git pull on the store host):
  ingest-rename-dryrun
  # or:
  ~/github.com/jovlinger/utils/shadup/.venv/bin/python \\
    ~/github.com/jovlinger/utils/shadup/ingest-rename-dryrun.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SHADUP = Path(__file__).resolve().parent
FILES = Path(os.environ.get("SHASRV_FILES", "/mnt/sdb2/music/flac/files"))

sys.path.insert(0, str(SHADUP))
from ingest_rename import propose_album_dirname  # noqa: E402


def main() -> int:
    if not FILES.is_dir():
        print(f"ERROR: missing FILES dir: {FILES}", file=sys.stderr)
        return 1
    n_rename = 0
    n_ok = 0
    n_skip = 0
    for album in sorted(
        p
        for p in FILES.iterdir()
        if p.is_dir() and p.name not in {"_tags"} and not p.name.startswith(".")
    ):
        target = propose_album_dirname(album)
        if target is None:
            print(f"SKIP  {album.name!r}  (no consensus)")
            n_skip += 1
        elif target == album.name:
            print(f"OK    {album.name!r}")
            n_ok += 1
        else:
            print(f"RENAME {album.name!r}  ->  {target!r}")
            n_rename += 1
    print(
        f"# summary: rename={n_rename} ok={n_ok} skip={n_skip}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
