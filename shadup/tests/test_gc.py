"""Tests for ``shadup gc``: reap every blob that has no live reference."""

from __future__ import annotations

import hashlib
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


def _blob(store: Path, digest: str) -> Path:
    return store / "data" / digest[:2] / digest


def test_gc_reaps_blob_left_by_soft_rm(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    digests = _store_album(store, files, db, "Album", {"a.flac": b"aaa"})
    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "-r", "Album"])
    assert _blob(store, digests["a.flac"]).is_file()

    _run(files, ["--shadir", str(store), "--db", str(db), "gc"])

    assert not _blob(store, digests["a.flac"]).exists()


def test_gc_reaps_earlier_orphan_that_rm_hard_left(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    old = _store_album(store, files, db, "Old", {"a.flac": b"old-bytes"})
    kept = _store_album(store, files, db, "Kept", {"a.flac": b"kept-bytes"})
    new = _store_album(store, files, db, "New", {"a.flac": b"new-bytes"})
    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "-r", "Old"])
    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "--hard", "-r", "New"])
    assert _blob(store, old["a.flac"]).is_file()
    assert not _blob(store, new["a.flac"]).exists()

    _run(files, ["--shadir", str(store), "--db", str(db), "gc"])

    assert not _blob(store, old["a.flac"]).exists()
    assert _blob(store, kept["a.flac"]).read_bytes() == b"kept-bytes"
    assert (files / "Kept" / "a.flac").is_symlink()


def test_gc_dry_run_changes_nothing(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    digests = _store_album(store, files, db, "Album", {"a.flac": b"aaa"})
    _run(files, ["--shadir", str(store), "--db", str(db), "rm", "-r", "Album"])

    result = _run(files, ["--shadir", str(store), "--db", str(db), "gc", "-n"])

    assert f"gc,{digests['a.flac']}" in result.stdout
    assert _blob(store, digests["a.flac"]).is_file()


def test_gc_removes_blob_with_no_database_row(tmp_path: Path) -> None:
    store, files, db = _layout(tmp_path)
    digest = _sha256(b"stray")
    blob = _blob(store, digest)
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"stray")
    _run(files, ["--shadir", str(store), "--db", str(db), "check"])

    _run(files, ["--shadir", str(store), "--db", str(db), "gc"])

    assert not blob.exists()


def test_rm_hard_and_gc_help_describe_different_scopes() -> None:
    hard = _run(Path("."), ["rm", "--help"])
    gc = _run(Path("."), ["gc", "--help"])
    assert "earlier soft-deletes" in hard.stdout
    assert "every blob" in gc.stdout
    assert "Takes no path" in gc.stdout
