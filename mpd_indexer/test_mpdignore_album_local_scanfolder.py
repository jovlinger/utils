#!/usr/bin/env python3
"""Album-local _tags cycles vs files/.mpdignore (Volumio scanFolder model).

Context: files/.mpdignore listing ``_tags`` / ``_meta`` only binds MPD's updater.
Volumio Node ``scanFolder`` walks the NFS tree itself and does not honor
``.mpdignore``. Album-local ``Album/_tags/...`` mirrors back into
``files/_tags`` and produce unbounded logical paths (ELOOP / ENAMETOOLONG).

This test requires a walk that terminates with O(real albums) directory visits
even when ``.mpdignore`` is present. On stock/main (no dont-walk) it is RED.
On branch d6d78baa (EfficientScan residual skip / done-set) it is GREEN.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from typing import Dict, Set


AUDIO = b"fLaC-album-local"
# Healthy walk is a handful of dirs; stock cycles for dozens before ELOOP.
VISIT_BUDGET = 40


def build_fixture(root: str) -> str:
    """gmk-like: .mpdignore + global _tags + album-local _tags back into it."""
    files = os.path.join(root, "files")
    album = os.path.join(files, "AlbumA")
    os.makedirs(album)
    with open(os.path.join(album, "01.flac"), "wb") as fh:
        fh.write(AUDIO)
    with open(os.path.join(files, ".mpdignore"), "w", encoding="ascii") as fh:
        fh.write("_tags\n_meta\n")
    tags_album = os.path.join(files, "_tags", "album")
    os.makedirs(tags_album)
    os.symlink(
        os.path.join("..", "..", "AlbumA"),
        os.path.join(tags_album, "AlbumA"),
    )
    local_tags = os.path.join(album, "_tags", "album")
    os.makedirs(local_tags)
    os.symlink(
        os.path.join("..", "..", "..", "_tags", "album", "AlbumA"),
        os.path.join(local_tags, "AlbumA"),
    )
    return files


def volumio_scan_folder(files: str, max_visits: int = VISIT_BUDGET) -> Dict[str, object]:
    """Follow every directory. Do not read .mpdignore (Volumio scanFolder)."""
    visits = 0
    hit_budget = False
    audio_unique: Set[str] = set()
    seen_logical: Set[str] = set()

    def walk(abs_dir: str, logical: str) -> None:
        nonlocal visits, hit_budget
        if visits >= max_visits:
            hit_budget = True
            return
        if logical in seen_logical:
            return
        seen_logical.add(logical)
        visits += 1
        try:
            names = os.listdir(abs_dir)
        except OSError:
            return
        for name in names:
            if name in (".", ".."):
                continue
            # Explicit: .mpdignore is not consulted (unlike MPD ExcludeList).
            p = os.path.join(abs_dir, name)
            log = logical.rstrip("/") + "/" + name
            try:
                if os.path.isdir(p):
                    walk(p, log)
                    if hit_budget:
                        return
                elif os.path.isfile(p) and name.lower().endswith(".flac"):
                    try:
                        audio_unique.add(os.path.realpath(p))
                    except OSError:
                        audio_unique.add(p)
            except OSError:
                continue

    walk(files, "")
    return {
        "mode": "volumio_scan_folder",
        "dir_visits": visits,
        "hit_budget": hit_budget,
        "audio_unique": len(audio_unique),
    }


def run_under_test(files: str) -> Dict[str, object]:
    """Prefer dont-walk EfficientScan when present (fork); else stock model."""
    try:
        from efficient_scan import EfficientScan  # type: ignore
    except ImportError:
        return volumio_scan_folder(files, max_visits=VISIT_BUDGET)

    scan = EfficientScan(files, os.devnull, 0, 10**9, alias_skip=False)
    try:
        m = scan.run()
        dir_visits = m.dirs_entered_real + m.dirs_entered_via_symlink
        return {
            "mode": "dontwalk",
            "dir_visits": dir_visits,
            "hit_budget": dir_visits >= VISIT_BUDGET,
            "audio_unique": m.audio_unique_realpaths,
        }
    finally:
        scan.close()


class MpdignoreAlbumLocalScanfolderTest(unittest.TestCase):
    def test_walk_terminates_despite_mpdignore(self) -> None:
        """``.mpdignore`` is present; walk must still stay under VISIT_BUDGET."""
        tmp = tempfile.mkdtemp(prefix="mpdignore-album-local-")
        try:
            files = build_fixture(tmp)
            ignore_path = os.path.join(files, ".mpdignore")
            self.assertTrue(os.path.isfile(ignore_path))
            with open(ignore_path, encoding="ascii") as fh:
                ignore_body = fh.read()
            self.assertIn("_tags", ignore_body)
            self.assertIn("_meta", ignore_body)

            row = run_under_test(files)
            self.assertEqual(
                row["audio_unique"],
                1,
                "song rows must stay one per real flac; got %r" % (row,),
            )
            self.assertFalse(
                row["hit_budget"],
                "walk blew the visit budget (mode=%s visits=%s budget=%s); "
                ".mpdignore does not protect Volumio-like scanners from "
                "album-local _tags cycles"
                % (row["mode"], row["dir_visits"], VISIT_BUDGET),
            )
            self.assertLess(
                int(row["dir_visits"]),
                VISIT_BUDGET,
                "dir_visits must stay O(real tree); got %r" % (row,),
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
