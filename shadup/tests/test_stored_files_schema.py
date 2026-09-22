"""Tests for stored_files path effective start/end schema and in-place upgrade."""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from pathlib import Path

import pytest

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _load_shadup() -> object:
    spec = importlib.util.spec_from_file_location("shadup_schema", SHADUP_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sh = _load_shadup()
PATH_EFFECTIVE_EPOCH = _sh.PATH_EFFECTIVE_EPOCH
init_db_schema = _sh.init_db_schema
open_database = _sh.open_database
upgrade_stored_files_schema = _sh.upgrade_stored_files_schema
_upsert_active_stored_file = _sh._upsert_active_stored_file
RFC3339_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _legacy_stored_files_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE stored_files (
            shasum TEXT NOT NULL,
            root TEXT NOT NULL,
            root_rel TEXT NOT NULL,
            dirpath TEXT NOT NULL,
            filename TEXT NOT NULL,
            deleted INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        INSERT INTO stored_files (shasum, root, root_rel, dirpath, filename, deleted)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        ("a" * 64, "/r", "files", "album", "a.flac"),
    )
    conn.commit()


def test_upgrade_adds_start_end_to_legacy_db(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        _legacy_stored_files_table(conn)

    with sqlite3.connect(db) as conn:
        assert upgrade_stored_files_schema(conn) is True
        conn.commit()
        cols = {row[1]: row for row in conn.execute("PRAGMA table_info(stored_files)")}
        assert "start" in cols
        assert "end" in cols
        assert cols["start"][3] == 1  # NOT NULL
        assert cols["end"][3] == 0  # nullable
        row = conn.execute(
            "SELECT start, end FROM stored_files WHERE filename = 'a.flac'"
        ).fetchone()
        assert row == (PATH_EFFECTIVE_EPOCH, None)

    with sqlite3.connect(db) as conn:
        assert upgrade_stored_files_schema(conn) is False


def test_init_db_schema_idempotent_on_fresh_db(tmp_path: Path) -> None:
    db = tmp_path / "fresh.db"
    with sqlite3.connect(db) as conn:
        init_db_schema(conn)
        conn.commit()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stored_files)")}
        assert {"start", "end"}.issubset(cols)

    conn = open_database(str(db))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(stored_files)")}
        assert {"start", "end"}.issubset(cols)
    finally:
        conn.close()


def test_upsert_sets_start_now_and_null_end(tmp_path: Path) -> None:
    db = tmp_path / "write.db"
    with sqlite3.connect(db) as conn:
        init_db_schema(conn)
        _upsert_active_stored_file(
            conn,
            "bb" * 32,
            "/files",
            "music",
            "album",
            "track.flac",
        )
        conn.commit()
        start, end = conn.execute(
            "SELECT start, end FROM stored_files WHERE filename = 'track.flac'"
        ).fetchone()
        assert RFC3339_RE.match(start)
        assert start != PATH_EFFECTIVE_EPOCH
        assert end is None


def test_end_dated_rows_excluded_from_active_reads(tmp_path: Path) -> None:
    db = tmp_path / "ended.db"
    with sqlite3.connect(db) as conn:
        init_db_schema(conn)
        conn.execute(
            """
            INSERT INTO stored_files
            (shasum, root, root_rel, dirpath, filename, deleted, start, end)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                "cc" * 32,
                "/files",
                "music",
                "old",
                "gone.flac",
                PATH_EFFECTIVE_EPOCH,
                "2020-01-01T00:00:00Z",
            ),
        )
        conn.commit()
        count = conn.execute(
            f"SELECT COUNT(*) FROM stored_files WHERE {_sh._ACTIVE_STORED_FILES_WHERE}"
        ).fetchone()[0]
        assert count == 0
