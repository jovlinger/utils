#!/usr/bin/env python3
"""Benchmark: don't-walk does not combinatorial-explode vs stock follow-all.

Builds anonymized ``files/AlbumNN`` trees with many ``_tags/album`` symlinks
onto those albums (same shape as the gmk browse mirrors, no real music).

Stock MPD-style walk counts every logical symlink path:
  audio_logical ~= albums * (1 + aliases_each)

Don't-walk (EfficientScan / MPD done-set) visits each real album once:
  audio_logical == albums
  sym_skip_done  > 0

Writes JSON proof to ``--out`` (default: mpd-combinatorial-proof.json).
Exit 0 only if every scale point passes the no-explosion assertions.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from typing import Any, Dict, List, Sequence, Tuple

import test_indexer_counts as tic


# (albums, aliases_each) -- ratios grow; dontwalk must stay flat.
DEFAULT_SCALES: Sequence[Tuple[int, int]] = (
    (5, 10),
    (10, 25),
    (20, 50),
    (40, 80),
)


def run_scale(albums: int, aliases_each: int) -> Dict[str, Any]:
    tmp = tempfile.mkdtemp(prefix="dontwalk-bench-")
    try:
        tic.build_fixture(tmp, albums=albums, aliases_each=aliases_each)
        root = os.path.join(tmp, "files")
        stock = tic._run_child("stock", root)
        dontwalk = tic._run_child("new", root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    expected_stock = albums * (1 + aliases_each)
    row: Dict[str, Any] = {
        "albums": albums,
        "aliases_each": aliases_each,
        "stock_audio_logical": stock["audio_logical"],
        "dontwalk_audio_logical": dontwalk["audio_logical"],
        "stock_dirs_logical": stock["dirs_logical"],
        "dontwalk_dirs_logical": dontwalk["dirs_logical"],
        "dontwalk_sym_skip_done": dontwalk.get("sym_skip_done", 0),
        "expected_stock_audio_logical": expected_stock,
        "ratio_stock_over_dontwalk": (
            stock["audio_logical"] / max(dontwalk["audio_logical"], 1)
        ),
    }

    errors: List[str] = []
    if stock["audio_logical"] != expected_stock:
        errors.append(
            "stock audio_logical %s != expected %s"
            % (stock["audio_logical"], expected_stock)
        )
    if dontwalk["audio_logical"] != albums:
        errors.append(
            "dontwalk audio_logical %s != albums %s (explosion)"
            % (dontwalk["audio_logical"], albums)
        )
    if dontwalk["audio_logical"] >= stock["audio_logical"]:
        errors.append("dontwalk did not beat stock path count")
    if int(dontwalk.get("sym_skip_done", 0)) <= 0:
        errors.append("dontwalk sym_skip_done expected > 0")
    # dirs: stock ~ O(albums*aliases); dontwalk ~ O(albums + tag bucket dirs)
    if dontwalk["dirs_logical"] > albums * 3 + 20:
        errors.append(
            "dontwalk dirs_logical %s too large for %s albums"
            % (dontwalk["dirs_logical"], albums)
        )
    row["ok"] = not errors
    row["errors"] = errors
    return row


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "mpd-combinatorial-proof.json",
        ),
        help="JSON proof output path",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    rows: List[Dict[str, Any]] = [run_scale(a, k) for a, k in DEFAULT_SCALES]
    failed = [r for r in rows if not r["ok"]]
    out: Dict[str, Any] = {
        "name": "dontwalk_no_combinatorial_explosion",
        "algorithm": "dont-walk / done-set (real dirs first; visited = realpath/inode)",
        "fixture": "anonymized AlbumNN + _tags/album symlink fan-out",
        "stock_model": "test_indexer_counts.stock_follow_all",
        "dontwalk_model": "efficient_scan.EfficientScan (alias_skip=False)",
        "rows": rows,
        "passed": len(failed) == 0,
        "conclusion": (
            "dontwalk audio_logical stays == albums at every scale; "
            "stock grows as albums*(1+aliases_each)"
        ),
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")
    print(json.dumps(out, indent=2))
    print("WROTE", args.out, file=sys.stderr)
    return 0 if out["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
