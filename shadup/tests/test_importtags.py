"""Tests for ``importtags`` (metatool export-json → shadup tag-add)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
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


def _run_importtags(
    cwd: Path,
    shadir: Path,
    metatool: str | Path,
    album: Path,
    *,
    reset: bool = False,
    dryrun: bool = False,
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
        "--metatool",
        str(metatool),
    ]
    if db is not None:
        cmd.extend(["--db", str(db)])
    if reset:
        cmd.append("--reset")
    if dryrun:
        cmd.append("--dryrun")
    cmd.append(str(album))
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True, env=env)


def _load_importtags():
    from importlib.util import module_from_spec, spec_from_file_location

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
    (album / "readme.txt").write_bytes(b"r")
    (album / "z.flac").write_bytes(b"a")
    with pytest.raises(mod.ImportTagsError, match="no symlink into sha store"):
        mod.pick_target_file(str(album), str(shadir))


def test_pick_target_errors_when_shadir_not_resolvable(tmp_path: Path) -> None:
    mod = _load_importtags()
    album = tmp_path / "only_album"
    album.mkdir()
    (album / "t.flac").write_bytes(b"x")
    with pytest.raises(mod.ImportTagsError, match="resolve sha store"):
        mod.pick_target_file(str(album), None)


def test_pick_target_prefers_earliest_symlink_into_shadir(tmp_path: Path) -> None:
    """Among blobs linked from the album, pick the symlink with oldest mtime."""
    mod = _load_importtags()

    shadir = tmp_path / "store"
    digest = "aa" * 32
    blob = shadir / "data" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"x")

    album = tmp_path / "al"
    album.mkdir()
    first = album / "zebra.flac"
    second = album / "a.flac"
    first.symlink_to(blob)
    second.symlink_to(blob)
    os.utime(first, (100, 100), follow_symlinks=False)
    os.utime(second, (900, 900), follow_symlinks=False)

    assert mod.pick_target_file(str(album), str(shadir)) == str(first)


def test_pick_target_descends_subdirs_when_top_level_is_directories_only(
    tmp_path: Path,
) -> None:
    """Album root may contain only subfolders (discs); symlinks live underneath."""
    mod = _load_importtags()

    shadir = tmp_path / "store"
    digest = "bb" * 32
    blob = shadir / "data" / digest[:2] / digest
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"y")

    album = tmp_path / "Frank Album"
    disc = album / "Frank Album 1,2"
    disc.mkdir(parents=True)
    track = disc / "01.flac"
    track.symlink_to(blob)

    assert mod.pick_target_file(str(album), str(shadir)) == str(track)


def test_pick_target_reads_shadir_from_db_meta_without_dot_shadir_on_disk(
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
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "importtags_mod", IMPORTTAGS_PKG / "importtags.py"
    )
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    payload = {
        "tag": ["live", "dup"],
        "genre": ["Rock", "dup"],
        "artist": "The Artist",
        "album": "The LP",
    }
    tags = mod.build_tags_from_export(payload)
    assert tags == [
        "live",
        "dup",
        "Rock",
        "artist:The Artist",
        "album:The LP",
    ]


def test_importtags_end_to_end(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"audio\n")

    _run_shadup(tmp_path, shadir, ["store", "work"])

    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' '{"tag": ["im"], "genre": ["gr"], "artist": "A1", "album": "B2"}'
            """
        )
    )
    os.chmod(fake_mt, 0o755)

    r = _run_importtags(tmp_path, shadir, fake_mt, album)
    assert r.returncode == 0, r.stderr

    tags = _db_tags_for_path(shadir, "work/disc/t.flac")
    assert tags == ["album:B2", "artist:A1", "gr", "im"]


def test_importtags_end_to_end_custom_db(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    custom_db = tmp_path / "data" / "x.db"
    custom_db.parent.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"audio\n")

    _run_shadup(tmp_path, shadir, ["store", "work"], db=custom_db)
    assert custom_db.is_file()

    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' '{"tag": ["im"], "genre": ["gr"], "artist": "A1", "album": "B2"}'
            """
        )
    )
    os.chmod(fake_mt, 0o755)

    r = _run_importtags(tmp_path, shadir, fake_mt, album, db=custom_db)
    assert r.returncode == 0, r.stderr

    tags = _db_tags_for_path(shadir, "work/disc/t.flac", db_path=custom_db)
    assert tags == ["album:B2", "artist:A1", "gr", "im"]


def test_importtags_reset_clears_before_add(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"audio\n")

    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "old"])

    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' '{"tag": ["new"], "genre": [], "artist": null, "album": null}'
            """
        )
    )
    os.chmod(fake_mt, 0o755)

    r = _run_importtags(tmp_path, shadir, fake_mt, album, reset=True)
    assert r.returncode == 0, r.stderr
    assert _db_tags_for_path(shadir, "work/disc/t.flac") == ["new"]


def test_importtags_skips_nondir(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    f = tmp_path / "notadir"
    f.write_text("x")
    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text("#!/bin/sh\nexit 99\n")
    os.chmod(fake_mt, 0o755)
    r = _run_importtags(tmp_path, shadir, fake_mt, f, check=False)
    assert r.returncode == 0


def test_importtags_skips_empty_export(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "keep"])

    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' '{"tag": [], "genre": [], "artist": null, "album": null}'
            """
        )
    )
    os.chmod(fake_mt, 0o755)
    r = _run_importtags(tmp_path, shadir, fake_mt, album)
    assert r.returncode == 0
    assert _db_tags_for_path(shadir, "work/disc/t.flac") == ["keep"]


def test_importtags_dryrun_does_not_touch_db(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "prior"])

    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' '{"tag": ["x"], "genre": [], "artist": null, "album": null}'
            """
        )
    )
    os.chmod(fake_mt, 0o755)

    before = _db_tags_for_path(shadir, "work/disc/t.flac")
    r = _run_importtags(tmp_path, shadir, fake_mt, album, dryrun=True)
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout
    assert "would tag-add" in r.stdout
    assert "resulting tags (after)" in r.stdout
    assert _db_tags_for_path(shadir, "work/disc/t.flac") == before


def test_importtags_dryrun_reset_shows_tag_rm(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"a\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/t.flac", "old"])

    fake_mt = tmp_path / "fake-metatool"
    fake_mt.write_text(
        textwrap.dedent(
            """\
            #!/bin/sh
            printf '%s\\n' '{"tag": ["new"], "genre": [], "artist": null, "album": null}'
            """
        )
    )
    os.chmod(fake_mt, 0o755)

    r = _run_importtags(tmp_path, shadir, fake_mt, album, dryrun=True, reset=True)
    assert r.returncode == 0, r.stderr
    assert "would tag-rm" in r.stdout
    assert '"old"' in r.stdout
