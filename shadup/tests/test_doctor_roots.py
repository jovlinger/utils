"""Tests for doctor root normalization and dual-root mv recovery."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(cwd: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SHADUP_PY), *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    store = tmp_path / "store"
    files = store / "files"
    data = store / "data"
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
) -> None:
    album_dir = files / album
    album_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in tracks.items():
        digest = _sha256(payload)
        blob = data / digest[:2] / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(payload)
        (album_dir / name).symlink_to(blob)
    _run(
        files,
        ["--shadir", str(tmp_path / "store"), "--db", str(db), "reindex-files", str(files)],
    )


def _insert_album_as_root_rows(db: Path, files: Path, album: str) -> None:
    """Simulate legacy ingest that used the album directory as stored_files.root."""
    album_root = str(files / album)
    album_root_rel = os.path.relpath(album_root, files)
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            """
            SELECT shasum, filename
            FROM stored_files
            WHERE dirpath = ? AND deleted = 0 AND end IS NULL
            """,
            (album,),
        ).fetchall()
        now = "2026-01-02T00:00:00Z"
        for shasum, filename in rows:
            conn.execute(
                """
                INSERT INTO stored_files
                (shasum, root, root_rel, dirpath, filename, deleted, start, end)
                VALUES (?, ?, ?, '.', ?, 0, ?, NULL)
                """,
                (shasum, album_root, album_root_rel, filename, now),
            )


def test_mv_fails_dual_root_then_doctor_allows_rename(tmp_path: Path) -> None:
    store, files, data, db = _layout(tmp_path)
    album = "Roxy.Music.Album"
    _store_album(tmp_path, files, data, db, album, {"01 track.dsf": b"a", "02 track.dsf": b"b"})
    _insert_album_as_root_rows(db, files, album)

    with pytest.raises(subprocess.CalledProcessError) as exc:
        _run(
            files,
            [
                "--shadir",
                str(store),
                "--db",
                str(db),
                "mv",
                album,
                "Roxy Music - Album",
            ],
        )
    assert "multiple store roots" in exc.value.stderr + exc.value.stdout

    _run(files, ["--shadir", str(store), "--db", str(db), "doctor"])

    _run(
        files,
        [
            "--shadir",
            str(store),
            "--db",
            str(db),
            "mv",
            album,
            "Roxy Music - Album",
        ],
    )

    assert not (files / album).exists()
    assert (files / "Roxy Music - Album" / "01 track.dsf").is_symlink()
    assert (files / "Roxy Music - Album" / "02 track.dsf").is_symlink()

    with sqlite3.connect(db) as conn:
        roots = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT root FROM stored_files WHERE deleted = 0 AND end IS NULL"
            )
        }
    assert roots == {str(files)}


def test_doctor_end_dates_duplicate_sha_path(tmp_path: Path) -> None:
    store, files, data, db = _layout(tmp_path)
    album = "Album"
    _store_album(tmp_path, files, data, db, album, {"a.flac": b"x"})
    _insert_album_as_root_rows(db, files, album)

    _run(files, ["--shadir", str(store), "--db", str(db), "doctor"])

    with sqlite3.connect(db) as conn:
        active = conn.execute(
            "SELECT COUNT(*) FROM stored_files WHERE deleted = 0 AND end IS NULL"
        ).fetchone()[0]
        ended = conn.execute(
            "SELECT COUNT(*) FROM stored_files WHERE end IS NOT NULL"
        ).fetchone()[0]
    assert active == 1
    assert ended == 1


def test_doctor_dry_run_samples_row_actions(tmp_path: Path) -> None:
    store, files, data, db = _layout(tmp_path)
    album = "Album"
    _store_album(tmp_path, files, data, db, album, {"a.flac": b"x", "b.flac": b"y"})
    _insert_album_as_root_rows(db, files, album)

    result = _run(
        files,
        [
            "--shadir",
            str(store),
            "--db",
            str(db),
            "doctor",
            "--dry-run",
            "-v=1",
        ],
    )
    assert "doctor sample 4/4 fixup rows (ratio=1.0)" in result.stdout
    assert "normalize " in result.stdout
    assert "end duplicate " in result.stdout
    assert "doctor rowid=" in result.stdout
    assert "doctor dry-run: no changes written" in result.stdout
    # No apply: both roots still present.
    with sqlite3.connect(db) as conn:
        roots = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT root FROM stored_files WHERE deleted = 0 AND end IS NULL"
            )
        }
    assert str(files) in roots
    assert any(r.endswith(album) for r in roots)


def test_store_from_album_dir_uses_canonical_files_root(tmp_path: Path) -> None:
    store, files, data, db = _layout(tmp_path)
    album = files / "Artist - Album"
    album.mkdir(parents=True)
    payload = b"track"
    digest = _sha256(payload)
    blob = data / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    (album / "01.flac").write_bytes(payload)

    _run(
        tmp_path,
        ["--shadir", str(store), "--db", str(db), "store", str(album)],
    )

    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT root, dirpath, filename FROM stored_files WHERE end IS NULL"
        ).fetchone()
    assert row == (str(files), "Artist - Album", "01.flac")
