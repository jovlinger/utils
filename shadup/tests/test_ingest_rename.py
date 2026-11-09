"""Tests for ingest_rename: tag consensus and post-ingest shadup mv."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SHADUP_DIR = Path(__file__).resolve().parent.parent
INGEST_PY = SHADUP_DIR / "ingest.py"
RENAME_PY = SHADUP_DIR / "ingest_rename.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_consensus_requires_two_thirds() -> None:
    rename = _load("ingest_rename_mod", RENAME_PY)
    pairs = [
        ("Peter Gabriel", "So"),
        ("Peter Gabriel", "So"),
        ("Wrong", "So"),
    ]
    assert rename.consensus_artist_album(pairs) == ("Peter Gabriel", "So")
    pairs2 = [
        ("A", "One"),
        ("B", "Two"),
        ("C", "Three"),
    ]
    assert rename.consensus_artist_album(pairs2) is None


def test_consensus_falls_back_to_cue() -> None:
    rename = _load("ingest_rename_mod", RENAME_PY)
    assert rename.consensus_artist_album(
        [], cue=("Peter Gabriel", "So")
    ) == ("Peter Gabriel", "So")
    assert rename.consensus_artist_album([], cue=("Various Artists", "Ost")) is None


def test_format_strips_the_and_rejects_va() -> None:
    rename = _load("ingest_rename_mod", RENAME_PY)
    assert rename.format_album_dirname("The Pogues", "Rum Sodomy & the Lash") == (
        "Pogues - Rum Sodomy & the Lash"
    )
    with pytest.raises(ValueError):
        rename.format_album_dirname("Various Artists", "Hits")


def test_read_flac_and_cue_propose_dirname(tmp_path: Path) -> None:
    rename = _load("ingest_rename_mod", RENAME_PY)
    album = tmp_path / "05 - 1986 - So (1986 UK PGCD 5)"
    album.mkdir()
    for i, title in enumerate(("Red Rain", "Sledgehammer", "Don't Give Up"), start=1):
        rename.write_minimal_flac_with_tags(
            album / f"{i:02d} - {title}.flac",
            {"ARTIST": "Peter Gabriel", "ALBUM": "So"},
        )
    (album / "00. Peter Gabriel - So.cue").write_text(
        'PERFORMER "Peter Gabriel"\nTITLE "So"\n'
        'FILE "01 - Red Rain.flac" WAVE\n'
        "  TRACK 01 AUDIO\n"
        '    TITLE "Red Rain"\n',
        encoding="utf-8",
    )
    (album / "folder.jpg").write_bytes(b"jpg")
    assert rename.propose_album_dirname(album) == "Peter Gabriel - So"


def test_ingest_renames_on_tag_consensus(tmp_path: Path) -> None:
    rename = _load("ingest_rename_mod", RENAME_PY)
    store_root = tmp_path / "store"
    data_dir = store_root / "data"
    files_dir = store_root / "files"
    db_path = tmp_path / "db" / "shadup.db"
    data_dir.mkdir(parents=True)
    files_dir.mkdir(parents=True)

    junk = "05 - 1986 - So (1986 UK PGCD 5)"
    src = tmp_path / "public" / junk
    src.mkdir(parents=True)
    for i in range(1, 4):
        rename.write_minimal_flac_with_tags(
            src / f"{i:02d} - t{i}.flac",
            {"ARTIST": "Peter Gabriel", "ALBUM": "So", "ALBUMARTIST": "Peter Gabriel"},
        )
    (src / "folder.jpg").write_bytes(b"art")

    env = {
        **os.environ,
        "SHASRV_STORE_ROOT": str(store_root),
        "SHASRV_DB": str(db_path),
    }
    proc = subprocess.run(
        [sys.executable, str(INGEST_PY), str(src)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ingest rename:" in proc.stderr
    assert (files_dir / "Peter Gabriel - So").is_dir()
    assert not (files_dir / junk).exists()
    assert list((files_dir / "Peter Gabriel - So").glob("*.flac"))
    # Artwork moved with the album dir.
    assert (files_dir / "Peter Gabriel - So" / "folder.jpg").exists()
