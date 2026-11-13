#!/usr/bin/env python3
"""Path-count and peak-RSS comparison: stock follow-all vs don't-walk.

The fixture is a few real albums plus many _tags symlinks onto those albums.
Stock counts every logical audio path. The don't-walk scan counts a real
directory once and does not descend a symlink whose real path is already done.
"""
from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest
from typing import Dict, Set


AUDIO = b"fLaC-fixture"


def _rss_kb() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def stock_follow_all(root: str) -> Dict[str, int]:
    """Follow every symlink. Count logical audio paths, not just unique files."""
    audio_logical = 0
    audio_real: Set[str] = set()
    dirs_logical = 0
    seen_logical: Set[str] = set()

    def walk(abs_dir: str, logical: str) -> None:
        nonlocal audio_logical, dirs_logical
        if logical in seen_logical:
            return
        seen_logical.add(logical)
        dirs_logical += 1
        try:
            names = os.listdir(abs_dir)
        except OSError:
            return
        for name in names:
            p = os.path.join(abs_dir, name)
            log = logical.rstrip("/") + "/" + name
            try:
                is_dir = os.path.isdir(p)
                is_file = os.path.isfile(p)
            except OSError:
                continue
            if is_dir:
                walk(p, log)
            elif is_file and name.lower().endswith(".flac"):
                audio_logical += 1
                try:
                    audio_real.add(os.path.realpath(p))
                except OSError:
                    audio_real.add(p)

    walk(root, "")
    return {
        "audio_logical": audio_logical,
        "audio_unique": len(audio_real),
        "dirs_logical": dirs_logical,
        "peak_rss_kb": _rss_kb(),
    }


def build_fixture(root: str, albums: int = 4, aliases_each: int = 25) -> None:
    files = os.path.join(root, "files")
    os.makedirs(files)
    for i in range(albums):
        album = os.path.join(files, "Album%02d" % i)
        os.makedirs(album)
        with open(os.path.join(album, "01.flac"), "wb") as fh:
            fh.write(AUDIO)
        bucket = os.path.join(files, "_tags", "album")
        os.makedirs(bucket, exist_ok=True)
        for k in range(aliases_each):
            link = os.path.join(bucket, "a%02d-alias%02d" % (i, k))
            os.symlink(os.path.join("..", "..", "Album%02d" % i), link)


def _run_child(mode: str, root: str) -> Dict[str, int]:
    here = os.path.dirname(os.path.abspath(__file__))
    code = r"""
import json, os, sys
sys.path.insert(0, %r)
import test_indexer_counts as t
from efficient_scan import EfficientScan
root, mode = sys.argv[1], sys.argv[2]
if mode == "stock":
    row = t.stock_follow_all(root)
else:
    scan = EfficientScan(root, os.devnull, 0, 10**9, alias_skip=False)
    try:
        m = scan.run()
    finally:
        scan.close()
    row = {
        "audio_logical": m.audio_files,
        "audio_unique": m.audio_unique_realpaths,
        "dirs_logical": m.dirs_entered_real + m.dirs_entered_via_symlink,
        "sym_skip_done": m.symlinks_skipped_done,
        "peak_rss_kb": m.peak_rss_kb,
    }
print(json.dumps(row))
""" % (
        here,
    )
    p = subprocess.run(
        [sys.executable, "-c", code, root, mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        check=False,
    )
    if p.returncode != 0:
        raise AssertionError("%s failed: %s" % (mode, p.stderr))
    return json.loads(p.stdout.strip().splitlines()[-1])


class IndexerCountTest(unittest.TestCase):
    def test_paths_and_rss(self) -> None:
        albums = 4
        aliases_each = 25
        tmp = tempfile.mkdtemp(prefix="idx-count-")
        try:
            build_fixture(tmp, albums=albums, aliases_each=aliases_each)
            root = os.path.join(tmp, "files")
            stock = _run_child("stock", root)
            new = _run_child("new", root)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        print(
            json.dumps(
                {"stock": stock, "dontwalk": new, "albums": albums, "aliases_each": aliases_each},
                indent=2,
                sort_keys=True,
            ),
            flush=True,
        )
        self.assertEqual(stock["audio_unique"], albums)
        self.assertEqual(new["audio_unique"], albums)
        self.assertEqual(stock["audio_logical"], albums * aliases_each + albums)
        self.assertEqual(new["audio_logical"], albums)
        self.assertGreater(new["sym_skip_done"], 0)
        self.assertLess(new["audio_logical"], stock["audio_logical"])
        self.assertGreater(stock["peak_rss_kb"], 0)
        self.assertGreater(new["peak_rss_kb"], 0)


if __name__ == "__main__":
    unittest.main()
