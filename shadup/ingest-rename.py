#!/usr/bin/env python3
"""Rename store album dirs from tag/cue consensus via ``shadup mv``.

Bare command does the renames (use the ``ingest-rename`` shell wrapper so the
store remounts rw). ``--dry-run`` prints SKIP / OK / RENAME only.

Usage:
  ingest-rename --dry-run
  ingest-rename
  ingest-rename --dry-run --album 'junk basename here'
  ingest-rename --album 'junk basename here'
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

SHADUP = Path(__file__).resolve().parent
sys.path.insert(0, str(SHADUP))

from ingest_rename import (  # noqa: E402
    propose_album_dirname,
    shadup_mv,
    unique_dirname,
)

FILES = Path(os.environ.get("SHASRV_FILES", "/mnt/sdb2/music/flac/files"))
STORE_ROOT = Path(os.environ.get("SHASRV_STORE_ROOT", "/mnt/sdb2/music/flac"))
DB_PATH = Path(
    os.environ.get(
        "SHASRV_DB",
        str(Path.home() / "Music" / "shasrv" / "shadup.db"),
    )
)
SHADUP_PY = SHADUP / "shadup.py"


def _iter_albums(files_dir: Path, only: list[str] | None) -> list[Path]:
    if only:
        out: list[Path] = []
        for name in only:
            path = files_dir / name
            if not path.is_dir():
                raise SystemExit(f"missing album dir: {path}")
            out.append(path)
        return out
    return sorted(
        p
        for p in files_dir.iterdir()
        if p.is_dir() and p.name not in {"_tags"} and not p.name.startswith(".")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rename top-level album dirs from tag/cue consensus. "
            "Bare run performs shadup mv; --dry-run prints only."
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print SKIP/OK/RENAME only; do not write",
    )
    parser.add_argument(
        "--album",
        action="append",
        default=[],
        metavar="BASENAME",
        help="limit to this album basename (repeatable)",
    )
    args = parser.parse_args(argv)
    do_write = not bool(args.dry_run)

    if not FILES.is_dir():
        print(f"ERROR: missing FILES dir: {FILES}", file=sys.stderr)
        return 1
    if do_write and not SHADUP_PY.is_file():
        print(f"ERROR: missing {SHADUP_PY}", file=sys.stderr)
        return 1

    n_rename = 0
    n_ok = 0
    n_skip = 0
    n_applied = 0
    mode_label = "DO" if do_write else "DRY-RUN"
    print(f"# mode={mode_label} files={FILES}", file=sys.stderr)

    for album in _iter_albums(FILES, args.album or None):
        target = propose_album_dirname(album)
        if target is None:
            print(f"SKIP  {album.name!r}  (no consensus)")
            n_skip += 1
            continue
        if target == album.name:
            print(f"OK    {album.name!r}")
            n_ok += 1
            continue
        final_name = unique_dirname(FILES, target) if do_write else target
        if do_write and final_name != target:
            print(
                f"RENAME {album.name!r}  ->  {final_name!r}  "
                f"(desired {target!r} taken)"
            )
        else:
            print(f"RENAME {album.name!r}  ->  {target!r}")
        n_rename += 1
        if not do_write:
            continue
        shadup_mv(
            store_root=STORE_ROOT,
            db_path=DB_PATH,
            shadup_py=SHADUP_PY,
            old_rel=album.name,
            new_rel=final_name,
            dry_run=False,
        )
        n_applied += 1

    print(
        f"# summary: rename={n_rename} ok={n_ok} skip={n_skip}"
        + (f" applied={n_applied}" if do_write else " applied=0 (dry-run)"),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
