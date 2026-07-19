"""Tests for ``importtags`` (``.meta.combined.json`` → shadup tag-add)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"
IMPORTTAGS_PKG = Path(__file__).resolve().parent.parent


def _db_tags_for_path(
    shadir: Path, relpath: str, *, db_path: Path | None = None
) -> list[str]:
    """Tags for the active row whose stored path equals *relpath* (shadup path shape)."""
    db_file = db_path if db_path is not None else shadir / ".shadup.db"
    want = os.path.normpath(relpath)
    with sqlite3.connect(db_file) as conn:
        rows = conn.execute(
            """
            SELECT shasum, root_rel, dirpath, filename
            FROM stored_files
            WHERE deleted = 0
            """
        ).fetchall()
    shasum: str | None = None
    for s, root_rel, dirpath, filename in rows:
        got = os.path.normpath(os.path.join(root_rel, dirpath, filename))
        if got == want:
            shasum = s
            break
    if not shasum:
        return []
    with sqlite3.connect(db_file) as conn:
        trow = conn.execute(
            "SELECT tags FROM sha_tags WHERE shasum = ?", (shasum,)
        ).fetchone()
    return json.loads(trow[0]) if trow else []


def _run_shadup(
    cwd: Path,
    shadir: Path,
    args: list[str],
    *,
    db: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SHADUP_PY), "--shadir", str(shadir)]
    if db is not None:
        cmd.extend(["--db", str(db)])
    cmd.extend(args)
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _write_combined(album: Path, tags: list[str]) -> None:
    (album / ".meta.combined.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "directory": str(album),
                "kind": "providers",
                "providers": [],
                "tags": tags,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_importtags(
    cwd: Path,
    shadir: Path,
    first_album: Path,
    *rest_albums,
    reset: bool = False,
    dryrun: bool = False,
    verbose: bool = False,
    debug: bool = False,
    db: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(IMPORTTAGS_PKG) + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    cmd = [
        sys.executable,
        "-m",
        "importtags",
        "--shadir",
        str(shadir),
    ]
    if db is not None:
        cmd.extend(["--db", str(db)])
    if reset:
        cmd.append("--reset")
    if dryrun:
        cmd.append("--dryrun")
    if verbose:
        cmd.append("-v")
    if debug:
        cmd.append("--debug")
    cmd.append(str(first_album))
    cmd.extend(str(a) for a in rest_albums)
    return subprocess.run(
        cmd, cwd=cwd, check=check, capture_output=True, text=True, env=env
    )


def _load_importtags():
    from importlib.util import module_from_spec, spec_from_file_location

    # Ensure sibling meta_combine is importable.
    sys.path.insert(0, str(IMPORTTAGS_PKG))
    spec = spec_from_file_location(
        "importtags_mod", IMPORTTAGS_PKG / "importtags.py"
    )
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_pick_target_errors_when_no_symlink_into_store(tmp_path: Path) -> None:
    mod = _load_importtags()
    album = tmp_path / "al"
    album.mkdir()
    shadir = tmp_path / "store"
    shadir.mkdir()
    (album / "local.flac").write_bytes(b"x")
    with pytest.raises(mod.ImportTagsError):
        mod.pick_target_file(str(album), str(shadir))


def test_pick_target_prefers_symlink_into_data(tmp_path: Path) -> None:
    mod = _load_importtags()
    shadir = tmp_path / "store"
    (shadir / "data" / "ab").mkdir(parents=True)
    blob = shadir / "data" / "ab" / ("ab" * 32)
    blob.write_bytes(b"x")
    album = tmp_path / "album"
    album.mkdir()
    track = album / "t.flac"
    track.symlink_to(blob)
    assert mod.pick_target_file(str(album), str(shadir)) == str(track)


def test_pick_target_uses_db_meta_shadir_when_no_dot_shadir(
    tmp_path: Path,
) -> None:
    """When only meta knows the store root (no ``.shadir`` dir for discovery)."""
    mod = _load_importtags()

    store = tmp_path / "flac"
    (store / "data").mkdir(parents=True)
    digest = "cc" * 32
    blob = store / "data" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"z")

    db_file = tmp_path / "tags.db"
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            "CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO meta (key, value) VALUES ('shadir', ?)",
            (str(store.resolve()),),
        )

    album = tmp_path / "elsewhere" / "Frank Album"
    disc = album / "Frank Album 1,2"
    disc.mkdir(parents=True)
    track = disc / "01.flac"
    track.symlink_to(blob)

    picked = mod.pick_target_file(str(album), None, db_path=str(db_file))
    assert picked == str(track)


def test_build_tags_unions_and_prefixes() -> None:
    mod = _load_importtags()
    payload = {
        "tag": ["live", "dup"],
        "genre": ["Rock", "dup"],
        "artist": "The Artist",
        "album": "The LP",
    }
    tags = mod.build_tags_from_export(payload)
    assert tags == [
        "tag;live",
        "tag;dup",
        "genre;Rock",
        "artist;The Artist",
        "album;The LP",
    ]


def test_importtags_end_to_end(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"audio\n")
    _write_combined(
        album, ["album;B2", "artist;A1", "genre;gr", "tag;im"]
    )

    _run_shadup(tmp_path, shadir, ["store", "work"])

    r = _run_importtags(tmp_path, shadir, album)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ".\n"

    tags = _db_tags_for_path(shadir, "work/disc/t.flac")
    assert tags == ["album;B2", "artist;A1", "genre;gr", "tag;im"]


def test_importtags_end_to_end_custom_db(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    custom_db = tmp_path / "data" / "x.db"
    custom_db.parent.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"audio\n")
    _write_combined(
        album, ["album;B2", "artist;A1", "genre;gr", "tag;im"]
    )

    _run_shadup(tmp_path, shadir, ["store", "work"], db=custom_db)
    assert custom_db.is_file()

    r = _run_importtags(tmp_path, shadir, album, db=custom_db)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ".\n"

    tags = _db_tags_for_path(shadir, "work/disc/t.flac", db_path=custom_db)
    assert tags == ["album;B2", "artist;A1", "genre;gr", "tag;im"]


def test_importtags_reset_clears_before_add(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"audio\n")
    _write_combined(album, ["tag;new"])

    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "old"])

    r = _run_importtags(tmp_path, shadir, album, reset=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ".\n"
    assert _db_tags_for_path(shadir, "work/disc/t.flac") == ["tag;new"]


def test_importtags_skips_nondir(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    f = tmp_path / "notadir"
    f.write_text("x")
    r = _run_importtags(tmp_path, shadir, f, check=False)
    assert r.returncode == 0
    assert r.stdout == ""


def test_importtags_skips_empty_combined(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _write_combined(album, [])
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "keep"])

    r = _run_importtags(tmp_path, shadir, album)
    assert r.returncode == 0
    assert r.stdout == ""
    assert _db_tags_for_path(shadir, "work/disc/t.flac") == ["keep"]


def test_importtags_skips_missing_combined(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    r = _run_importtags(tmp_path, shadir, album)
    assert r.returncode == 0
    assert r.stdout == ""


def test_importtags_verbose_prints_plan_and_result(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _write_combined(album, ["tag;x"])
    _run_shadup(tmp_path, shadir, ["store", "work"])

    r = _run_importtags(tmp_path, shadir, album, verbose=True)
    assert r.returncode == 0, r.stderr
    assert "[import]" in r.stdout
    assert "tag-add:" in r.stdout
    assert "tags (after):" in r.stdout


def test_importtags_debug_prints_one_line_per_album(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _write_combined(album, ["tag;x", "tag;y"])
    _run_shadup(tmp_path, shadir, ["store", "work"])

    r = _run_importtags(tmp_path, shadir, album, debug=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().startswith("[import]")
    assert "\t" in r.stdout
    assert "2 tags" in r.stdout
    assert ".\n" not in r.stdout


def test_importtags_two_albums_one_process_dots_one_line(tmp_path: Path) -> None:
    """Quiet dots must stay on one line when one importtags handles many dirs."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    a1 = work / "a1"
    a2 = work / "a2"
    a1.mkdir(parents=True)
    a2.mkdir(parents=True)
    (a1 / "t.flac").write_bytes(b"a\n")
    (a2 / "u.flac").write_bytes(b"b\n")
    _write_combined(a1, ["tag;t"])
    _write_combined(a2, ["tag;t"])
    _run_shadup(tmp_path, shadir, ["store", "work"])

    r = _run_importtags(tmp_path, shadir, a1, a2)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "..\n"


def test_importtags_dryrun_does_not_touch_db(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _write_combined(album, ["tag;x"])
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "prior"])

    before = _db_tags_for_path(shadir, "work/disc/t.flac")
    r = _run_importtags(tmp_path, shadir, album, dryrun=True)
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout
    assert "would tag-add" in r.stdout
    assert "resulting tags (after)" in r.stdout
    assert _db_tags_for_path(shadir, "work/disc/t.flac") == before


def test_importtags_dryrun_reset_shows_tag_clear(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _write_combined(album, ["tag;new"])
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "old"])

    r = _run_importtags(tmp_path, shadir, album, dryrun=True, reset=True)
    assert r.returncode == 0, r.stderr
    assert "would tag-clear" in r.stdout
    assert '"old"' in r.stdout
