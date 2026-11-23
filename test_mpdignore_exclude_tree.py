#!/usr/bin/env python3
"""Red/green: .mpdignore excludes an unrelated directory tree from the walk.

Fixture: music album plus a fat ``noise/`` tree of non-library files.
When ``noise`` is listed in ``files/.mpdignore``, the walk must not enter
``noise`` (or any child). Album audio still indexes.

Requires EfficientScan with mpdignore honor (fork). Absent that, this is RED.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from typing import List, Set


AUDIO = b"fLaC-keep"


def build_fixture(root: str) -> str:
    files = os.path.join(root, "files")
    album = os.path.join(files, "AlbumA")
    os.makedirs(album)
    with open(os.path.join(album, "01.flac"), "wb") as fh:
        fh.write(AUDIO)

    noise = os.path.join(files, "noise", "deep", "wider")
    os.makedirs(noise)
    with open(os.path.join(noise, "dump.bin"), "wb") as fh:
        fh.write(b"x" * 64)
    with open(os.path.join(noise, "trap.flac"), "wb") as fh:
        fh.write(AUDIO)
    # sibling junk at noise root
    with open(os.path.join(files, "noise", "readme.txt"), "w", encoding="ascii") as fh:
        fh.write("not music\n")

    with open(os.path.join(files, ".mpdignore"), "w", encoding="ascii") as fh:
        fh.write("noise\n")
    return files


class MpdignoreExcludeTreeTest(unittest.TestCase):
    def test_noise_tree_not_walked_when_mpdignored(self) -> None:
        try:
            from efficient_scan import EfficientScan
        except ImportError as e:
            self.fail("EfficientScan required: %s" % e)

        tmp = tempfile.mkdtemp(prefix="mpdignore-exclude-")
        try:
            files = build_fixture(tmp)
            scan = EfficientScan(files, os.devnull, 0, 10**9, alias_skip=False)
            try:
                m = scan.run()
                entries: Set[str] = set(scan.directory_entries)
                visited: List[str] = list(scan.visit_order)
                songs: List[str] = list(scan.song_logical_paths)
            finally:
                scan.close()

            self.assertEqual(m.audio_unique_realpaths, 1)
            self.assertEqual(m.audio_files, 1)
            self.assertTrue(any(s.endswith("/AlbumA/01.flac") for s in songs))

            noise_hits = [
                p
                for p in list(entries) + visited + songs
                if "/noise" in p.replace("\\", "/")
            ]
            self.assertEqual(
                noise_hits,
                [],
                "noise/ must not be walked when listed in .mpdignore; got %r" % noise_hits,
            )
            self.assertNotIn("/noise", entries)
            self.assertGreater(
                getattr(m, "mpdignore_skipped", 0),
                0,
                "walker must report at least one mpdignore skip",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
