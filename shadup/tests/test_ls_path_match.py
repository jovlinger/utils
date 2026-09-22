"""Tests for ``ls`` path filtering: prefix-from-root and segment-subsequence tails."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _load_shadup() -> object:
    spec = importlib.util.spec_from_file_location("shadup_ls_match", SHADUP_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sh = _load_shadup()
path_matches_ls_query = _sh.path_matches_ls_query
list_children = _sh.list_children


@pytest.mark.parametrize(
    ("stored", "query", "expect"),
    [
        ("files/a/b.flac", "files/a/b.flac", True),
        ("files/a/b.flac", "files/a", True),
        ("music/files/a/b.flac", "files/a/b.flac", True),
        ("music/files/a/b.flac", "a/b.flac", True),
        ("music/files/a/b.flac", "files/a", True),
        ("work/a.txt", "a.txt", True),
        ("work/a.txt", "nomatch/a.txt", False),
        ("files/VA - Album/x.flac", "VA - Album/x.flac", True),
        ("files/VA - Album/x.flac", "VA - Album", True),
    ],
)
def test_path_matches_ls_query(stored: str, query: str, expect: bool) -> None:
    assert path_matches_ls_query(stored, query) is expect


def test_list_children_tail_query(tmp_path: Path) -> None:
    """Stored path includes a prefix not in the query; tail segments still match."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    db = shadir / ".shadup.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE stored_files (
                shasum TEXT NOT NULL,
                root TEXT NOT NULL,
                root_rel TEXT NOT NULL,
                dirpath TEXT NOT NULL,
                filename TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE sha_tags (shasum TEXT NOT NULL PRIMARY KEY, tags TEXT NOT NULL);
            """
        )
        conn.execute(
            """
            INSERT INTO stored_files
            (shasum, root, root_rel, dirpath, filename, deleted)
            VALUES (?, ?, ?, ?, ?, 0)
            """,
            (
                "ab" * 32,
                "/r",
                "music",
                "files/VA - Example",
                "01 - track.flac",
            ),
        )
        _sh.upgrade_stored_files_schema(conn)
    with sqlite3.connect(db) as conn:
        rows = list_children(conn, ["VA - Example/01 - track.flac"], False, False)
    assert len(rows) == 1
    assert rows[0][0] == "music/files/VA - Example/01 - track.flac"
    assert rows[0][1] == "ab" * 32


def test_ls_subprocess_tail(tmp_path: Path) -> None:
    """End-to-end: ``ls`` with a path tail finds the row."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    deep = work / "files" / "Some Album"
    deep.mkdir(parents=True)
    f = deep / "song.flac"
    f.write_bytes(b"flac-bytes-here\n")

    subprocess.run(
        [sys.executable, str(SHADUP_PY), "--shadir", str(shadir), "store", str(work)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    tail = "Some Album/song.flac"
    result = subprocess.run(
        [
            sys.executable,
            str(SHADUP_PY),
            "--shadir",
            str(shadir),
            "ls",
            tail,
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "song.flac" in result.stdout
    assert result.stdout.count("\n") >= 1
