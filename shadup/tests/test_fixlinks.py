"""Tests for ``fixlinks``: blob path resolution next to ``files/`` and safety."""

from __future__ import annotations

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(
    cwd: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SHADUP_PY), *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def _init_db(
    db_path: Path,
    *,
    root: str,
    digest: str,
    root_rel: str,
    filename: str,
    dirpath: str = "",
) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS stored_files (
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
        CREATE UNIQUE INDEX IF NOT EXISTS stored_files_unique_rel
        ON stored_files(shasum, root_rel, dirpath, filename)
        """
    )
    conn.execute(
        """
        INSERT INTO stored_files (shasum, root, root_rel, dirpath, filename, deleted)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (digest, root, root_rel, dirpath, filename),
    )
    conn.commit()
    conn.close()


def test_fixlinks_finds_blob_next_to_files_root(tmp_path: Path) -> None:
    """Blob at ``dirname(files)/xx/hash`` (not under ``.shadir``): repair broken symlink."""
    music = tmp_path / "music"
    files_root = music / "files"
    shadir = files_root / ".shadir"
    shadir.mkdir(parents=True)
    album = files_root / "album"
    album.mkdir(parents=True)

    data = b"hello fixlinks sibling layout"
    digest = _sha256(data)
    blob_dir = music / digest[:2]
    blob_dir.mkdir(parents=True)
    blob_path = blob_dir / digest
    blob_path.write_bytes(data)

    track = album / "track.flac"
    track.symlink_to("/totally/broken/target")

    db_path = tmp_path / "t.db"
    _init_db(
        db_path,
        root=str(files_root.resolve()),
        digest=digest,
        root_rel="album",
        filename="track.flac",
    )

    r = _run(
        files_root,
        [
            "--shadir",
            str(shadir),
            "--db",
            str(db_path),
            "fixlinks",
            "album",
        ],
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert track.is_symlink()
    assert track.readlink() == blob_path.resolve()


def test_fixlinks_when_shadir_is_broad_flac_tree(tmp_path: Path) -> None:
    """Mirror ``--shadir .../flac`` with ``flac/{files,data}`` -- blobs under ``data/xx/...``."""
    music = tmp_path / "music"
    flac = music / "flac"
    files_root = flac / "files"
    album = files_root / "Blues"
    album.mkdir(parents=True)

    data = b"broad flac tree root containing files/ and data/ hash buckets"
    digest = _sha256(data)
    blob_dir = flac / "data" / digest[:2]
    blob_dir.mkdir(parents=True)
    blob_path = blob_dir / digest
    blob_path.write_bytes(data)

    track = album / "16-track.flac"
    track.symlink_to("/missing/previously/so_resolve_must_find_flac_prefix")

    db_path = tmp_path / "broad_flac.db"
    _init_db(
        db_path,
        root=str(files_root.resolve()),
        digest=digest,
        root_rel="Blues",
        filename="16-track.flac",
    )

    r = _run(
        files_root,
        [
            "--shadir",
            str(flac),
            "--db",
            str(db_path),
            "fixlinks",
            "Blues",
        ],
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert track.readlink() == blob_path.resolve()


def test_fixlinks_recurses_into_subdirectories(tmp_path: Path) -> None:
    """Directory PATH walks nested dirs by default (no ``-r`` required)."""
    music = tmp_path / "music"
    files_root = music / "files"
    shadir = files_root / ".shadir"
    shadir.mkdir(parents=True)
    album = files_root / "album"
    sub = album / "sub"
    sub.mkdir(parents=True)

    data = b"nested track"
    digest = _sha256(data)
    blob_dir = music / digest[:2]
    blob_dir.mkdir(parents=True)
    blob_path = blob_dir / digest
    blob_path.write_bytes(data)

    track = sub / "t.flac"
    track.symlink_to("/broken")

    db_path = tmp_path / "nested.db"
    _init_db(
        db_path,
        root=str(files_root.resolve()),
        digest=digest,
        root_rel="album",
        dirpath="sub",
        filename="t.flac",
    )

    r = _run(
        files_root,
        [
            "--shadir",
            str(shadir),
            "--db",
            str(db_path),
            "fixlinks",
            "album",
        ],
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert track.readlink() == blob_path.resolve()


def test_fixlinks_accepts_single_symlink_path(tmp_path: Path) -> None:
    """A PATH that is itself a symlink is fixed without passing its parent directory."""
    music = tmp_path / "music"
    files_root = music / "files"
    shadir = files_root / ".shadir"
    shadir.mkdir(parents=True)
    album = files_root / "album"
    album.mkdir(parents=True)

    data = b"x"
    digest = _sha256(data)
    blob_dir = music / digest[:2]
    blob_dir.mkdir(parents=True)
    blob_path = blob_dir / digest
    blob_path.write_bytes(data)

    track = album / "one.flac"
    track.symlink_to("/bad")

    db_path = tmp_path / "one.db"
    _init_db(
        db_path,
        root=str(files_root.resolve()),
        digest=digest,
        root_rel="album",
        filename="one.flac",
    )

    r = _run(
        files_root,
        [
            "--shadir",
            str(shadir),
            "--db",
            str(db_path),
            "fixlinks",
            str(album / "one.flac"),
        ],
    )
    assert r.returncode == 0, r.stderr + r.stdout
    assert track.readlink() == blob_path.resolve()


def test_fixlinks_skips_when_no_blob_anywhere(tmp_path: Path) -> None:
    """Do not rewrite symlinks when digest has no on-disk blob."""
    root = tmp_path / "lib"
    shadir = root / ".shadir"
    shadir.mkdir(parents=True)
    f = root / "a.flac"
    h = _sha256(b"only in db")
    f.symlink_to("/nope")

    db_path = tmp_path / "empty.db"
    _init_db(
        db_path,
        root=str(root.resolve()),
        digest=h,
        root_rel=".",
        filename="a.flac",
    )

    r = _run(
        root,
        [
            "--shadir",
            str(shadir),
            "--db",
            str(db_path),
            "fixlinks",
            ".",
        ],
    )
    assert r.returncode == 0
    assert f.readlink() == Path("/nope")
