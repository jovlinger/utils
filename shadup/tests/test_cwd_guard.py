"""Tests for the cwd-inside-shadir guard.

The guard only applies to actions that walk or write the user's working tree
(``store`` and ``extract``). All other actions should run fine from inside
shadir.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _run(
    cwd: Path, shadir: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SHADUP_PY), "--shadir", str(shadir), *args]
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _setup_with_one_file(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create shadir, store one file, return (tmp_path, shadir, stored_symlink)."""
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    src = work / "hello.txt"
    src.write_bytes(b"hello\n")
    _run(tmp_path, shadir, ["store", "work"])
    assert src.is_symlink()
    return tmp_path, shadir, src


def test_store_rejects_cwd_inside_shadir(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    inside = shadir / "inside"
    inside.mkdir()
    (inside / "x.txt").write_bytes(b"x\n")

    result = _run(inside, shadir, ["store", "."], check=False)
    assert result.returncode != 0
    assert "cwd must not be inside shadir for store" in result.stderr


def test_extract_rejects_cwd_inside_shadir(tmp_path: Path) -> None:
    _cwd, shadir, _link = _setup_with_one_file(tmp_path)
    inside = shadir / "sub"
    inside.mkdir()

    result = _run(inside, shadir, ["extract", "work"], check=False)
    assert result.returncode != 0
    assert "cwd must not be inside shadir for extract" in result.stderr


def test_ls_allowed_from_inside_shadir(tmp_path: Path) -> None:
    _cwd, shadir, _link = _setup_with_one_file(tmp_path)
    inside = shadir / "sub"
    inside.mkdir()

    result = _run(inside, shadir, ["ls"])
    assert "hello.txt" in result.stdout


def test_rmhash_allowed_from_inside_shadir(tmp_path: Path) -> None:
    """A DB-only action should not be blocked by cwd being inside shadir."""
    _cwd, shadir, _link = _setup_with_one_file(tmp_path)
    inside = shadir / "sub"
    inside.mkdir()

    dummy_hash = "0" * 64
    result = _run(inside, shadir, ["rmhash", dummy_hash])
    assert result.returncode == 0


def test_tag_add_allowed_from_inside_shadir(tmp_path: Path) -> None:
    """Path resolution for tag-add still works from inside shadir."""
    _cwd, shadir, link = _setup_with_one_file(tmp_path)
    inside = shadir / "sub"
    inside.mkdir()

    result = _run(inside, shadir, ["tag-add", str(link), "red"])
    assert result.returncode == 0


def test_check_allowed_from_inside_shadir(tmp_path: Path) -> None:
    """``check`` is read-only; cwd inside shadir must not block it."""
    _cwd, shadir, _link = _setup_with_one_file(tmp_path)
    inside = shadir / "sub"
    inside.mkdir()

    result = _run(inside, shadir, ["check"])
    assert result.returncode == 0
    assert "check ok" in result.stdout
