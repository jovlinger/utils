"""Tests for ``importtags`` (metatool export-json → shadup tag-add)."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

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


def test_pick_target_prefers_readme_over_audio(tmp_path: Path) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "importtags_mod", IMPORTTAGS_PKG / "importtags.py"
    )
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    album = tmp_path / "al"
    album.mkdir()
    (album / "z.flac").write_bytes(b"a")
    (album / "readme.txt").write_bytes(b"r")
    assert mod.pick_target_file(str(album)) == str(album / "readme.txt")


def test_pick_target_audio_only_then_first_lex(tmp_path: Path) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "importtags_mod", IMPORTTAGS_PKG / "importtags.py"
    )
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    album = tmp_path / "al"
    album.mkdir()
    (album / "b.flac").write_bytes(b"b")
    (album / "a.flac").write_bytes(b"a")
    assert mod.pick_target_file(str(album)) == str(album / "a.flac")


def test_pick_target_audio_and_image_uses_image(tmp_path: Path) -> None:
    from importlib.util import module_from_spec, spec_from_file_location

    spec = spec_from_file_location(
        "importtags_mod", IMPORTTAGS_PKG / "importtags.py"
    )
    assert spec and spec.loader
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)

    album = tmp_path / "al"
    album.mkdir()
    (album / "z.flac").write_bytes(b"a")
    (album / "cover.jpg").write_bytes(b"j")
    assert mod.pick_target_file(str(album)) == str(album / "cover.jpg")


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
    (album / "notes.txt").write_bytes(b"notes\n")
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

    tags = _db_tags_for_path(shadir, "work/disc/notes.txt")
    assert tags == ["album:B2", "artist:A1", "gr", "im"]


def test_importtags_end_to_end_custom_db(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    custom_db = tmp_path / "data" / "x.db"
    custom_db.parent.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "notes.txt").write_bytes(b"notes\n")
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

    tags = _db_tags_for_path(shadir, "work/disc/notes.txt", db_path=custom_db)
    assert tags == ["album:B2", "artist:A1", "gr", "im"]


def test_importtags_reset_clears_before_add(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "notes.txt").write_bytes(b"notes\n")

    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/notes.txt", "old"])

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
    assert _db_tags_for_path(shadir, "work/disc/notes.txt") == ["new"]


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
    (album / "notes.txt").write_bytes(b"n\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/notes.txt", "keep"])

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
    assert _db_tags_for_path(shadir, "work/disc/notes.txt") == ["keep"]


def test_importtags_dryrun_does_not_touch_db(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "notes.txt").write_bytes(b"n\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/notes.txt", "prior"])

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

    before = _db_tags_for_path(shadir, "work/disc/notes.txt")
    r = _run_importtags(tmp_path, shadir, fake_mt, album, dryrun=True)
    assert r.returncode == 0, r.stderr
    assert "[dry-run]" in r.stdout
    assert "would tag-add" in r.stdout
    assert "resulting tags (after)" in r.stdout
    assert _db_tags_for_path(shadir, "work/disc/notes.txt") == before


def test_importtags_dryrun_reset_shows_tag_rm(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    album = work / "disc"
    album.mkdir(parents=True)
    (album / "notes.txt").write_bytes(b"n\n")
    _run_shadup(tmp_path, shadir, ["store", "work"])
    _run_shadup(tmp_path, shadir, ["tag-add", "work/disc/notes.txt", "old"])

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
