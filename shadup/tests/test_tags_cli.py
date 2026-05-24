"""CLI tests for tag subcommands (PATH-addressed, AWS-style)."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _load_shadup() -> object:
    spec = importlib.util.spec_from_file_location("shadup_mod", SHADUP_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sh = _load_shadup()


def _run(
    cwd: Path, shadir: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SHADUP_PY), "--shadir", str(shadir), *args]
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _db_tags(shadir: Path, shasum: str) -> list[str]:
    with sqlite3.connect(shadir / ".shadup.db") as conn:
        row = conn.execute(
            "SELECT tags FROM sha_tags WHERE shasum = ?", (shasum,)
        ).fetchone()
    return json.loads(row[0]) if row else []


def _setup_stored(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    """Create shadir, store one file, return (cwd, shadir, stored_symlink, shasum)."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    src = work / "hello.txt"
    src.write_bytes(b"hello-shadup\n")
    shasum = _sh.sha256_file(str(src))
    _run(tmp_path, shadir, ["store", "work"])
    assert src.is_symlink(), "expected --store to replace file with symlink"
    return tmp_path, shadir, src, shasum


def test_tag_add_then_rm_via_path(tmp_path: Path) -> None:
    """tag-add + tag-rm round-trip through a symlink-into-shadir path."""
    cwd, shadir, stored_link, shasum = _setup_stored(tmp_path)

    _run(cwd, shadir, ["tag-add", str(stored_link), "alpha", "beta"])
    assert _db_tags(shadir, shasum) == ["alpha", "beta"]

    _run(cwd, shadir, ["tag-add", str(stored_link), "gamma"])
    assert _db_tags(shadir, shasum) == ["alpha", "beta", "gamma"]

    _run(cwd, shadir, ["tag-rm", str(stored_link), "beta", "gamma"])
    assert _db_tags(shadir, shasum) == ["alpha"]


def test_tag_add_via_regular_file(tmp_path: Path) -> None:
    """tag-add on a regular file hashes it on-the-fly."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    loose = tmp_path / "loose.bin"
    loose.write_bytes(b"unstored content\n")
    shasum = _sh.sha256_file(str(loose))

    _run(tmp_path, shadir, ["tag-add", str(loose), "untracked"])
    assert _db_tags(shadir, shasum) == ["untracked"]


def test_tag_add_rejects_bare_hash(tmp_path: Path) -> None:
    """A raw sha256 hex string is not a valid PATH for tag-add."""
    _cwd, shadir, _link, shasum = _setup_stored(tmp_path)

    result = _run(tmp_path, shadir, ["tag-add", shasum, "nope"], check=False)
    assert result.returncode != 0
    assert "cannot resolve path to stored file" in result.stderr
    assert _db_tags(shadir, shasum) == []


def test_tag_add_rejects_missing_path(tmp_path: Path) -> None:
    """A non-existent path is rejected."""
    _cwd, shadir, _link, _shasum = _setup_stored(tmp_path)

    result = _run(
        tmp_path, shadir, ["tag-add", str(tmp_path / "no-such"), "x"], check=False
    )
    assert result.returncode != 0
    assert "cannot resolve path to stored file" in result.stderr


def test_tag_add_requires_at_least_one_tag(tmp_path: Path) -> None:
    """argparse enforces PATH TAG [TAG ...] at parse time."""
    _cwd, shadir, stored_link, _shasum = _setup_stored(tmp_path)

    result = _run(tmp_path, shadir, ["tag-add", str(stored_link)], check=False)
    assert result.returncode != 0


def test_tag_clear_removes_all_tags_for_path(tmp_path: Path) -> None:
    cwd, shadir, stored_link, shasum = _setup_stored(tmp_path)
    _run(cwd, shadir, ["tag-add", str(stored_link), "a", "b"])
    assert _db_tags(shadir, shasum) == ["a", "b"]

    _run(cwd, shadir, ["tag-clear", str(stored_link)])
    assert _db_tags(shadir, shasum) == []


def _count_sha_tags_rows(shadir: Path) -> int:
    with sqlite3.connect(shadir / ".shadup.db") as conn:
        row = conn.execute("SELECT COUNT(*) FROM sha_tags").fetchone()
    return int(row[0]) if row else 0


def test_clear_tags_no_force_warns_and_noop(tmp_path: Path) -> None:
    cwd, shadir, stored_link, shasum = _setup_stored(tmp_path)
    _run(cwd, shadir, ["tag-add", str(stored_link), "x"])
    assert _count_sha_tags_rows(shadir) == 1

    r = _run(cwd, shadir, ["clear-tags"], check=True)
    assert "no action taken" in r.stderr
    assert _count_sha_tags_rows(shadir) == 1
    assert _db_tags(shadir, shasum) == ["x"]


def test_clear_tags_force_wipes_table(tmp_path: Path) -> None:
    cwd, shadir, stored_link, shasum = _setup_stored(tmp_path)
    _run(cwd, shadir, ["tag-add", str(stored_link), "x"])
    assert _count_sha_tags_rows(shadir) == 1

    _run(cwd, shadir, ["clear-tags", "-f"])
    assert _count_sha_tags_rows(shadir) == 0
    assert _db_tags(shadir, shasum) == []
