#!/usr/bin/env python3
"""Normative don't-walk contract for todo:d6d78baa (MPD database updater).

These tests enshrine the Body / AC. A patch that hard-skips or deletes
``_tags`` / ``_meta`` by basename (IsAliasDirName, alias_skip) FAILS them.

Patch instructions (verbatim intent from ticket Body + AC + WI 0018):

1. Classify each directory entry with lstat: a symlink is not a real directory.
   Do not key the walk off CIFS reification.

2. Walk each directory depth-first.

3. Visit real entries before symlinks.

4. Within a class, sort by name: digit, then letter, then other
   (so ``_meta`` precedes ``_tags``).

5. On entry to a real directory: add its real path to the don't-walk set,
   then index that directory, including its songs.

6. After real entries are done, visit symlinks. Resolve each to a real path.
   - If that path is already in the don't-walk set: do NOT descend and do NOT
     add its songs again; STILL record the symlink as a directory entry so
     lsinfo can show the tag tree.
   - If the target is not in the set: follow it, including a target outside
     the music root / on another drive, and index it as a real directory.

7. Song rows exist once per real file. ``_tags`` is a directory index over
   those rows. A skip that also drops the directory line fails this ticket.

8. Fixture: one real album plus a ``_tags`` symlink to it must yield one song
   row and an lsinfo directory under ``_tags``.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from typing import List, Set, Tuple

from efficient_scan import EfficientScan, name_class, sort_key


AUDIO = b"fLaC-contract"


def _build_contract_fixture(root: str) -> Tuple[str, str]:
    """files/AlbumA with one flac; _tags/album/a -> AlbumA; off-root album B."""
    files = os.path.join(root, "files")
    album_a = os.path.join(files, "AlbumA")
    os.makedirs(album_a)
    with open(os.path.join(album_a, "01.flac"), "wb") as fh:
        fh.write(AUDIO)

    tags_album = os.path.join(files, "_tags", "album")
    os.makedirs(tags_album)
    # real dirs under _tags so NFS/local layout is represented; leaf is symlink
    os.symlink(
        os.path.join("..", "..", "AlbumA"),
        os.path.join(tags_album, "AlbumA"),
    )

    # outside music root (stand-in for "another drive")
    other = os.path.join(root, "other_drive", "AlbumB")
    os.makedirs(other)
    with open(os.path.join(other, "01.flac"), "wb") as fh:
        fh.write(AUDIO)
    os.symlink(other, os.path.join(files, "offdrive-AlbumB"))

    return files, other


class DontWalkContractTest(unittest.TestCase):
    def test_instructions_forbid_name_based_alias_wipe(self) -> None:
        """Hard-skip of _tags/_meta by basename is not the ticket."""
        # Documented anti-pattern; keep the string so greps find it.
        forbidden = "IsAliasDirName"
        self.assertEqual(forbidden, "IsAliasDirName")
        tmp = tempfile.mkdtemp(prefix="dw-forbid-")
        try:
            files, _ = _build_contract_fixture(tmp)
            # alias_skip=True is the Python cousin of IsAliasDirName
            scan = EfficientScan(files, os.devnull, 0, 10**9, alias_skip=True)
            try:
                scan.run()
                entries = scan.directory_entries
            finally:
                scan.close()
            self.assertIn(
                "/_tags",
                entries,
                "alias_skip=True must not be used for acceptance: "
                "_tags must remain a directory entry",
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_one_song_and_tags_directory_entry(self) -> None:
        """WI 0018 fixture: one song row; _tags still appears as directories."""
        tmp = tempfile.mkdtemp(prefix="dw-fixture-")
        try:
            files, other = _build_contract_fixture(tmp)
            scan = EfficientScan(files, os.devnull, 0, 10**9, alias_skip=False)
            try:
                m = scan.run()
                entries = set(scan.directory_entries)
                songs = set(scan.song_logical_paths)
            finally:
                scan.close()

            self.assertEqual(m.audio_unique_realpaths, 2)  # AlbumA + AlbumB
            self.assertEqual(m.audio_files, 2)
            self.assertEqual(m.path_under_tags_audio, 0)

            # Song paths are canonical album paths only (not under _tags)
            self.assertTrue(any(s.endswith("/AlbumA/01.flac") for s in songs))
            self.assertFalse(any("/_tags/" in s and s.endswith(".flac") for s in songs))

            # Directory index (lsinfo stand-in) must expose the tag tree
            self.assertIn("/_tags", entries)
            self.assertIn("/_tags/album", entries)
            self.assertIn("/_tags/album/AlbumA", entries)

            # Off-root / other-drive target still indexed
            self.assertTrue(
                any("AlbumB" in s and s.endswith(".flac") for s in songs)
                or any(s.endswith("/offdrive-AlbumB/01.flac") for s in songs)
            )
            self.assertGreater(m.symlinks_skipped_done, 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_real_before_symlink_and_name_class_order(self) -> None:
        tmp = tempfile.mkdtemp(prefix="dw-order-")
        try:
            files = os.path.join(tmp, "files")
            os.makedirs(files)
            # names spanning classes; letter dirs + _meta/_tags + digit
            for name in ("B_letter", "A_letter", "1digit", "_meta", "_tags"):
                os.makedirs(os.path.join(files, name))
            os.symlink("A_letter", os.path.join(files, "sym_to_A"))
            with open(os.path.join(files, "A_letter", "01.flac"), "wb") as fh:
                fh.write(AUDIO)

            scan = EfficientScan(files, os.devnull, 0, 10**9, alias_skip=False)
            try:
                scan.run()
                order = list(scan.visit_order)
            finally:
                scan.close()

            # Among first-level directory visits from root, reals before symlink
            top = [v for v in order if v.count("/") == 1]
            names = [v.lstrip("/").split("/")[0] for v in top]
            if "sym_to_A" in names:
                self.assertLess(names.index("A_letter"), names.index("sym_to_A"))

            # digit, letter, other
            self.assertEqual(name_class("1digit"), 0)
            self.assertEqual(name_class("A_letter"), 1)
            self.assertEqual(name_class("_meta"), 2)
            self.assertEqual(name_class("_tags"), 2)
            sorted_names = sorted(
                ["B_letter", "A_letter", "1digit", "_meta", "_tags"],
                key=sort_key,
            )
            self.assertEqual(
                sorted_names,
                ["1digit", "A_letter", "B_letter", "_meta", "_tags"],
            )
            # _meta before _tags within "other"
            self.assertLess(sorted_names.index("_meta"), sorted_names.index("_tags"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_skip_done_still_records_directory_not_songs(self) -> None:
        tmp = tempfile.mkdtemp(prefix="dw-skipdir-")
        try:
            files, _ = _build_contract_fixture(tmp)
            # many aliases onto the same album
            bucket = os.path.join(files, "_tags", "album")
            for i in range(5):
                os.symlink(
                    os.path.join("..", "..", "AlbumA"),
                    os.path.join(bucket, "alias%02d" % i),
                )
            scan = EfficientScan(files, os.devnull, 0, 10**9, alias_skip=False)
            try:
                m = scan.run()
                entries = set(scan.directory_entries)
                songs = list(scan.song_logical_paths)
            finally:
                scan.close()

            self.assertEqual(m.audio_files, 2)
            self.assertGreaterEqual(m.symlinks_skipped_done, 5)
            for i in range(5):
                self.assertIn("/_tags/album/alias%02d" % i, entries)
            self.assertEqual(
                sum(1 for s in songs if s.endswith("01.flac") and "AlbumA" in s),
                1,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
