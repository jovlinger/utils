"""Tests for ``shadup rm``: soft-delete paths and remove the library tree."""

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


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    store = tmp_path / "store"
    files = store / "files"
    files.mkdir(parents=True)
    (store / "data").mkdir()
    return store, files, tmp_path / "t.db"


def _store_album(
    store: Path,
    files: Path,
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
        blob = store / "data" / digest[:2] / digest
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(payload)
        (album_dir / name).symlink_to(blob)
    _run(files, ["--shadir", str(store), "--db", str(db), "reindex-files", str(files)])
    return digests


def _active_names(db: Path, album: str) -> list[str]:
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            """
            SELECT filename FROM stored_files
            WHERE dirpath = ? AND deleted = 0 AND end IS NULL
            ORDER BY filename
            """,
            (album,),
        ).fetchall()
    return [row[0] for row in rows]


def test_rm_recursive_removes_library_tree_and_keeps_blob(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    digests = _store_album(store, files, db, "Album", {"a.flac": b"aaa", "b.flac": b"bbb"})
    (files / "Album" / ".meta.json").write_text("{}", encoding="utf-8")

    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "-r", "Album"])

    assert not (files / "Album").exists()
    assert _active_names(db, "Album") == []
    blob = store / "data" / digests["a.flac"][:2] / digests["a.flac"]
    assert blob.read_bytes() == b"aaa"


def test_rm_one_file_leaves_the_album_and_the_blob(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    digests = _store_album(store, files, db, "Album", {"a.flac": b"aaa", "b.flac": b"bbb"})

    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "Album/a.flac"])

    assert not (files / "Album" / "a.flac").exists()
    assert (files / "Album" / "b.flac").is_symlink()
    assert (files / "Album").is_dir()
    assert _active_names(db, "Album") == ["b.flac"]
    blob = store / "data" / digests["a.flac"][:2] / digests["a.flac"]
    assert blob.is_file()


def test_rm_dry_run_changes_nothing(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    _store_album(store, files, db, "Album", {"a.flac": b"aaa"})

    result = _run(
        files,
        ["--shadir", str(store), "--db", str(db), "rm", "-n", "-r", "Album"],
    )

    assert "rm,Album/a.flac" in result.stdout
    assert (files / "Album" / "a.flac").is_symlink()
    assert _active_names(db, "Album") == ["a.flac"]


def test_rm_directory_without_recursive_leaves_rows(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    _store_album(store, files, db, "Album", {"a.flac": b"aaa"})

    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "Album"])

    assert (files / "Album" / "a.flac").is_symlink()
    assert _active_names(db, "Album") == ["a.flac"]
