"""Tests for ``shadup mv``: disk rename + stored_files start/end history."""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SHADUP_PY), *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    store = tmp_path / "store"
    files = store / "files"
    data = store / "data"
    shadir = store
    files.mkdir(parents=True)
    data.mkdir(parents=True)
    db = tmp_path / "t.db"
    return store, files, data, db


def _store_album(
    tmp_path: Path,
    files: Path,
    data: Path,
    db: Path,
    album: str,
    tracks: dict[str, bytes],
) -> dict[str, str]:
    album_dir = files / album
    album_dir.mkdir(parents=True, exist_ok=True)
    digests: dict[str, str] = {}
    for name, payload in tracks.items():
        digest = _sha256(payload)
        digests[name] = digest
        blob = data / digest[:2] / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(payload)
        (album_dir / name).symlink_to(blob)
    _run(
        files,
        ["--shadir", str(tmp_path / "store"), "--db", str(db), "reindex-files", str(files)],
    )
    return digests


def _active_rows(db: Path) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(
            """
            SELECT shasum, root_rel, dirpath, filename, start, end
            FROM stored_files
            WHERE deleted = 0 AND end IS NULL
            ORDER BY dirpath, filename
            """
        ).fetchall()


def _all_rows(db: Path) -> list[tuple]:
    with sqlite3.connect(db) as conn:
        return conn.execute(
            """
            SELECT root_rel, dirpath, filename, start, end
            FROM stored_files
            ORDER BY rowid
            """
        ).fetchall()


def test_mv_renames_file_and_records_history(tmp_path: Path) -> None:
    _store, files, data, db = _layout(tmp_path)
    _store_album(tmp_path, files, data, db, "Album", {"a.flac": b"a", "b.flac": b"b"})

    assert (files / "Album" / "a.flac").is_symlink()
    _run(
        files,
        [
            "--shadir",
            str(tmp_path / "store"),
            "--db",
            str(db),
            "mv",
            "Album/a.flac",
            "Album/renamed.flac",
        ],
    )

    assert not (files / "Album" / "a.flac").exists()
    assert (files / "Album" / "renamed.flac").is_symlink()
    active = _active_rows(db)
    assert len(active) == 2
    names = sorted(row[3] for row in active)
    assert names == ["b.flac", "renamed.flac"]
    all_rows = _all_rows(db)
    ended = [row for row in all_rows if row[4] is not None]
    assert len(ended) == 1
    assert ended[0][2] == "a.flac"


def test_mv_renames_directory_tree(tmp_path: Path) -> None:
    _store, files, data, db = _layout(tmp_path)
    _store_album(
        tmp_path,
        files,
        data,
        db,
        "Old Name",
        {"one.flac": b"1", "two.flac": b"2"},
    )

    _run(
        files,
        [
            "--shadir",
            str(tmp_path / "store"),
            "--db",
            str(db),
            "mv",
            "Old Name",
            "New Name",
        ],
    )

    assert not (files / "Old Name").exists()
    assert (files / "New Name" / "one.flac").is_symlink()
    assert (files / "New Name" / "two.flac").is_symlink()
    active = _active_rows(db)
    assert len(active) == 2
    assert all(row[2] == "New Name" for row in active)
    assert len(_all_rows(db)) == 4


def test_mv_dry_run_leaves_disk_and_db_unchanged(tmp_path: Path) -> None:
    _store, files, data, db = _layout(tmp_path)
    _store_album(tmp_path, files, data, db, "Album", {"a.flac": b"a"})

    before = _all_rows(db)
    _run(
        files,
        [
            "--shadir",
            str(tmp_path / "store"),
            "--db",
            str(db),
            "mv",
            "--dry-run",
            "Album",
            "Renamed",
        ],
    )
    assert (files / "Album" / "a.flac").is_symlink()
    assert _all_rows(db) == before


def test_upgrade_replaces_full_unique_index(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            CREATE TABLE stored_files (
                shasum TEXT NOT NULL,
                root TEXT NOT NULL,
                root_rel TEXT NOT NULL,
                dirpath TEXT NOT NULL,
                filename TEXT NOT NULL,
                deleted INTEGER NOT NULL DEFAULT 0,
                start TEXT NOT NULL DEFAULT '1970-01-01T00:00:00Z',
                end TEXT
            );
            CREATE UNIQUE INDEX stored_files_unique_rel
            ON stored_files(shasum, root_rel, dirpath, filename);
            """
        )
    _run(tmp_path, ["--db", str(db), "--shadir", str(tmp_path / "s"), "check"])
    with sqlite3.connect(db) as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(stored_files)")}
    assert "stored_files_unique_active_rel" in indexes
    assert "stored_files_unique_rel" not in indexes
