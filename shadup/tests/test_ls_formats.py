"""Output-format tests for ``ls`` (aka lspath) and ``lshash``.

Both commands emit a flat, space-delimited, column-padded table. ``lshash``
now includes tags alongside the hash/path, matching ``lspath``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import subprocess
import sys
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(
    cwd: Path,
    shadir: Path,
    args: list[str],
    *,
    machine: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SHADUP_PY), "--shadir", str(shadir), *args]
    stdin = None if machine else subprocess.DEVNULL
    # When stdout is not a TTY, shadup picks machine (CSV) mode automatically.
    # Force pretty mode by routing stdout through a pseudo-TTY-like wrapper:
    # simplest portable approach is to *disable* CSV by setting the env hint
    # isn't available, so instead we just use machine-mode assertions when we
    # need determinism, and parse pretty mode loosely.
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        stdin=stdin,
    )


def _setup_two_files(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Two distinct files stored, with tags on one. Returns (cwd, shadir, digests)."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    a = work / "a.txt"
    b = work / "b.txt"
    a.write_bytes(b"aaa\n")
    b.write_bytes(b"bbb\n")
    digests = {"a.txt": _sha256(a.read_bytes()), "b.txt": _sha256(b.read_bytes())}
    _run(tmp_path, shadir, ["store", "work"])
    _run(tmp_path, shadir, ["tag-add", str(a), "red", "blue"])
    return tmp_path, shadir, digests


def test_lshash_machine_mode_emits_flat_rows_with_tags(tmp_path: Path) -> None:
    """Machine (CSV) mode: one row per (hash, path) with tags column."""
    cwd, shadir, digests = _setup_two_files(tmp_path)

    result = _run(cwd, shadir, ["lshash"])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    by_path = {row[1]: row for row in rows}

    assert "work/a.txt" in by_path
    assert "work/b.txt" in by_path

    a_row = by_path["work/a.txt"]
    b_row = by_path["work/b.txt"]
    assert a_row[0] == digests["a.txt"]
    assert b_row[0] == digests["b.txt"]
    assert sorted(csv_json_tags(a_row[2])) == ["blue", "red"]
    assert csv_json_tags(b_row[2]) == []
    assert a_row[3] == "0"
    assert b_row[3] == "0"


def csv_json_tags(cell: str) -> list[str]:
    import json as _json

    return list(_json.loads(cell))


def test_lspath_machine_mode_still_lists_tags(tmp_path: Path) -> None:
    """Sanity: lspath machine mode is unchanged (path, shasum, tags-json, deleted)."""
    cwd, shadir, digests = _setup_two_files(tmp_path)

    result = _run(cwd, shadir, ["ls"])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    by_path = {row[0]: row for row in rows}
    assert by_path["work/a.txt"][1] == digests["a.txt"]
    assert sorted(csv_json_tags(by_path["work/a.txt"][2])) == ["blue", "red"]
    assert by_path["work/a.txt"][3] == "0"


def test_lshash_shows_tags_for_filtered_hash(tmp_path: Path) -> None:
    """Filtering by hash still includes the tags column."""
    cwd, shadir, digests = _setup_two_files(tmp_path)

    result = _run(cwd, shadir, ["lshash", digests["a.txt"]])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    assert len(rows) == 1
    shasum, path, tags_json, deleted = rows[0]
    assert shasum == digests["a.txt"]
    assert path == "work/a.txt"
    assert sorted(csv_json_tags(tags_json)) == ["blue", "red"]
    assert deleted == "0"


def test_ls_alltags_single_file_matches_plain_ls(tmp_path: Path) -> None:
    """``--alltags`` on a file path uses per-file tags (same rows as plain ``ls``)."""
    shadir = tmp_path / "sha"
    shadir.mkdir()
    files_root = tmp_path / "files"
    album = files_root / "album"
    album.mkdir(parents=True)
    (album / "t.flac").write_bytes(b"x")

    _run(tmp_path, shadir, ["store", "files"])
    _run(tmp_path, shadir, ["tag-add", "files/album/t.flac", "alpha"])

    plain = _run(tmp_path, shadir, ["ls", "files/album/t.flac"])
    alltags = _run(tmp_path, shadir, ["ls", "--alltags", "files/album/t.flac"])
    assert plain.stdout == alltags.stdout


def test_ls_alltags_resolves_files_root_when_shadir_not_adjacent_to_files(
    tmp_path: Path,
) -> None:
    """``--alltags`` finds ``files/`` via DB + cwd when ``dirname(shadir)/files`` is wrong."""
    blob_store = tmp_path / "blob_store"
    blob_store.mkdir()
    lib_home = tmp_path / "music" / "flac"
    files_root = lib_home / "files"
    album = files_root / "album"
    album.mkdir(parents=True)
    (album / "x.flac").write_bytes(b"x")

    _run(lib_home, blob_store, ["store", "files"])
    _run(lib_home, blob_store, ["tag-add", "files/album/x.flac", "orphan"])

    result = _run(lib_home, blob_store, ["ls", "--alltags", "files/album"])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    assert len(rows) >= 1
    tag_cell = next(r[1] for r in rows if r[0].replace("\\", "/").endswith("files/album"))
    assert sorted(csv_json_tags(tag_cell)) == ["orphan"]


def test_ls_alltags_directory_unions_descendant_tags(tmp_path: Path) -> None:
    """``--alltags`` on a directory lists aggregated tags for that directory tree."""
    shadir = tmp_path / "sha"
    shadir.mkdir()
    files_root = tmp_path / "files"
    album = files_root / "album"
    album.mkdir(parents=True)
    (album / "a.flac").write_bytes(b"a")
    (album / "b.flac").write_bytes(b"b")

    _run(tmp_path, shadir, ["store", "files"])
    _run(tmp_path, shadir, ["tag-add", "files/album/a.flac", "rock"])
    _run(tmp_path, shadir, ["tag-add", "files/album/b.flac", "jazz"])

    result = _run(tmp_path, shadir, ["ls", "--alltags", "files/album"])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    album_row = None
    norm_tail = str(Path("files/album"))
    for row in rows:
        if len(row) >= 2 and row[0].replace("\\", "/").endswith(norm_tail):
            album_row = row
            break
    assert album_row is not None
    assert sorted(csv_json_tags(album_row[1])) == ["jazz", "rock"]


def test_lshash_show_deleted_column(tmp_path: Path) -> None:
    """With -d, deleted rows appear with deleted=1."""
    cwd, shadir, _digests = _setup_two_files(tmp_path)

    _run(cwd, shadir, ["rmpath", "work/a.txt"])

    result = _run(cwd, shadir, ["lshash", "-d"])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    by_path = {row[1]: row for row in rows}

    assert by_path["work/a.txt"][3] == "1"
    assert by_path["work/b.txt"][3] == "0"
