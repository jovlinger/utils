"""Tests for extract materialization modes."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from pytest import MonkeyPatch

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"

_SPEC = importlib.util.spec_from_file_location("shadup", SHADUP_PY)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def _run(
    cwd: Path, shadir: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SHADUP_PY), "--shadir", str(shadir), *args]
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def _setup_stored_file(tmp_path: Path) -> tuple[Path, Path, Path, Path, bytes]:
    shadir = tmp_path / "store"
    shadir.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    src = work / "hello.txt"
    content = b"hello-shadup\n"
    src.write_bytes(content)

    _run(tmp_path, shadir, ["store", "work"])
    assert src.is_symlink()
    blob = src.resolve(strict=True)
    assert blob.read_bytes() == content
    return tmp_path, shadir, src, blob, content


def test_extract_help_describes_copy_hardlink_and_symlink_modes() -> None:
    result = subprocess.run(
        [sys.executable, str(SHADUP_PY), "extract", "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    help_text = result.stdout
    assert "hardlink when the target is on the same filesystem as shadir" in help_text
    assert "copy when it is on a different filesystem" in help_text
    assert "With -s / --symlink, extract writes symlinks" in help_text
    assert "-s, --symlink" in help_text


def test_extract_default_hardlinks_on_same_filesystem(tmp_path: Path) -> None:
    cwd, shadir, restored, blob, content = _setup_stored_file(tmp_path)

    _run(cwd, shadir, ["extract", "work"])

    assert not restored.is_symlink()
    assert restored.read_bytes() == content
    restored_stat = os.stat(restored)
    blob_stat = os.stat(blob)
    assert restored_stat.st_dev == blob_stat.st_dev
    assert restored_stat.st_ino == blob_stat.st_ino


def test_extract_symlink_option_creates_symlink(tmp_path: Path) -> None:
    cwd, shadir, restored, blob, content = _setup_stored_file(tmp_path)
    _run(cwd, shadir, ["extract", "work"])
    assert not restored.is_symlink()

    _run(cwd, shadir, ["extract", "-s", "work"])

    assert restored.is_symlink()
    assert restored.resolve(strict=True) == blob.resolve(strict=True)
    assert restored.read_bytes() == content


def test_extract_helper_copies_on_different_filesystems(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    blob = tmp_path / "blob"
    content = b"copy me\n"
    blob.write_bytes(content)
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    dest = dest_dir / "blob"

    def different_filesystems(_store_path: str, _dest_dir: str) -> bool:
        return False

    monkeypatch.setattr(_MOD, "_same_filesystem", different_filesystems)

    size = _MOD._link_copy_or_symlink(str(blob), str(dest), str(dest_dir), False)

    assert size == len(content)
    assert dest.read_bytes() == content
    assert not os.path.samefile(blob, dest)
