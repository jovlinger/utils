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


def test_lshash_show_deleted_column(tmp_path: Path) -> None:
    """With -d, deleted rows appear with deleted=1."""
    cwd, shadir, _digests = _setup_two_files(tmp_path)

    _run(cwd, shadir, ["rmpath", "work/a.txt"])

    result = _run(cwd, shadir, ["lshash", "-d"])
    rows = list(csv.reader(io.StringIO(result.stdout)))
    by_path = {row[1]: row for row in rows}

    assert by_path["work/a.txt"][3] == "1"
    assert by_path["work/b.txt"][3] == "0"
