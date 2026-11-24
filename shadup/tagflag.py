#!/usr/bin/env python3
"""tagflag: full musicology / tag / import / _tags refresh pipeline for songs.

Operator entry around ``postingest`` (musicscan -> .meta.combined.json ->
importtags -> refresh-extracted-tags). Prefer this name when re-tagging the
library; ``postingest`` remains the stage implementation.

  tagflag                  # default store files/ root
  tagflag PATH...          # one or more album / disc directories
  tagflag -f               # reprocess all: force provider refetch + retag
  tagflag -f PATH...

Remount is owned by postingest. Env defaults match postingest
(``POSTINGEST_STORE_ROOT``, ``POSTINGEST_DB``, ``POSTINGEST_PROVIDERS``).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent


def find_postingest() -> Path:
    """Locate the postingest script (sibling, env, PATH, then conventional clone)."""
    env = os.environ.get("TAGFLAG_POSTINGEST") or os.environ.get("POSTINGEST")
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p.resolve()
    sibling = _SCRIPT_DIR / "postingest"
    if sibling.is_file():
        return sibling
    marker = Path.home() / ".local" / "bin" / ".tagflag-postingest"
    if marker.is_file():
        recorded = Path(marker.read_text(encoding="utf-8").strip()).expanduser()
        if recorded.is_file():
            return recorded.resolve()
    which = shutil.which("postingest")
    if which:
        return Path(which).resolve()
    conventional = (
        Path.home() / "github.com" / "jovlinger" / "utils" / "shadup" / "postingest"
    )
    if conventional.is_file():
        return conventional
    raise SystemExit(
        "tagflag: cannot find postingest (set TAGFLAG_POSTINGEST or install "
        "utils/shadup beside this script)"
    )


def build_postingest_argv(
    roots: Sequence[Path],
    *,
    force: bool,
    dry_run: bool,
    verbose: int,
    extra: Sequence[str],
) -> list[str]:
    """Translate tagflag flags into postingest argv (no program name)."""
    argv: list[str] = []
    if force:
        argv.extend(["--force_provider", "--force_retag"])
    if dry_run:
        argv.append("--dry-run")
    if verbose:
        argv.append("-" + ("v" * verbose))
    argv.extend(extra)
    argv.extend(str(p) for p in roots)
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tagflag",
        description=(
            "Run the full musicology/tag/ingest pipeline for songs "
            "(postingest: musicscan, combine, importtags, refresh _tags)."
        ),
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="Reprocess all: musicscan --force and rebuild every combined file.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass through to postingest (no writes).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (passed to postingest).",
    )
    parser.add_argument(
        "roots",
        nargs="*",
        type=Path,
        help=(
            "Album or disc directories under the store (default: postingest "
            "files root)."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    postingest = find_postingest()
    post_argv = build_postingest_argv(
        args.roots,
        force=args.force,
        dry_run=args.dry_run,
        verbose=args.verbose,
        extra=[],
    )
    cmd: List[str] = [sys.executable, str(postingest), *post_argv]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        return int(exc.returncode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
