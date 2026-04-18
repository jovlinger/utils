"""Integration tests for ``ingest.py`` (ensures it drives shadup's new CLI)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

INGEST_PY = Path(__file__).resolve().parent.parent / "ingest.py"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _layout(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Create the store-root layout ingest.py expects."""
    store_root = tmp_path / "store"
    data_dir = store_root / "data"
    files_dir = store_root / "files"
    db_path = tmp_path / "db" / "shadup.db"
    data_dir.mkdir(parents=True)
    files_dir.mkdir(parents=True)
    return store_root, data_dir, files_dir, db_path


def _run_ingest(
    cwd: Path,
    store_root: Path,
    db_path: Path,
    targets: list[Path],
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "SHASRV_STORE_ROOT": str(store_root),
        "SHASRV_DB": str(db_path),
    }
    cmd = [sys.executable, str(INGEST_PY), *(str(t) for t in targets)]
    return subprocess.run(
        cmd, cwd=cwd, check=True, capture_output=True, text=True, env=env
    )


def _payload_path(data_dir: Path, digest: str) -> Path:
    return data_dir / digest[:2] / digest


def _assert_stored_symlink(link: Path, data_dir: Path, digest: str) -> None:
    assert link.is_symlink(), f"expected symlink at {link}"
    resolved = link.resolve()
    payload = _payload_path(data_dir, digest)
    assert resolved == payload.resolve(), f"{link} -> {resolved} expected {payload}"
    assert payload.is_file(), f"missing payload {payload}"


def test_ingest_directory_layout_and_cleanup(tmp_path: Path) -> None:
    """Ingest a directory: payloads in data/, symlinks in files/<name>/, src pruned."""
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)

    src_dir = tmp_path / "album"
    (src_dir / "sub").mkdir(parents=True)
    file_a = src_dir / "a.txt"
    file_b = src_dir / "sub" / "b.txt"
    file_a.write_bytes(b"aaa\n")
    file_b.write_bytes(b"bbb\n")
    digest_a = _sha256(file_a.read_bytes())
    digest_b = _sha256(file_b.read_bytes())

    _run_ingest(tmp_path, store_root, db_path, [src_dir])

    _assert_stored_symlink(files_dir / "album" / "a.txt", data_dir, digest_a)
    _assert_stored_symlink(files_dir / "album" / "sub" / "b.txt", data_dir, digest_b)

    assert not file_a.exists(), "source file should be removed after ingest"
    assert not file_b.exists(), "source file should be removed after ingest"
    assert not src_dir.exists(), "empty source dir should be pruned"


def test_ingest_single_file_uses_parent_name_as_prefix(tmp_path: Path) -> None:
    """Ingesting a loose file places it under files/<parent-dir-name>/."""
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)

    loose_dir = tmp_path / "loose"
    loose_dir.mkdir()
    loose = loose_dir / "track.txt"
    loose.write_bytes(b"single\n")
    digest = _sha256(loose.read_bytes())

    _run_ingest(tmp_path, store_root, db_path, [loose])

    _assert_stored_symlink(files_dir / "loose" / "track.txt", data_dir, digest)
    assert not loose.exists(), "source file should be removed after ingest"


def test_ingest_uses_new_cli_payload_is_plain_file(tmp_path: Path) -> None:
    """Payload in data/ is a regular file (shadup store moved it), not a symlink."""
    store_root, data_dir, _files_dir, db_path = _layout(tmp_path)

    loose_dir = tmp_path / "in"
    loose_dir.mkdir()
    loose = loose_dir / "x.bin"
    content = b"payload-content\n"
    loose.write_bytes(content)
    digest = _sha256(content)

    _run_ingest(tmp_path, store_root, db_path, [loose])

    payload = _payload_path(data_dir, digest)
    assert payload.is_file(), f"payload missing at {payload}"
    assert not payload.is_symlink()
    assert payload.read_bytes() == content
