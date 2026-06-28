"""Integration tests for ``ingest.py`` (ensures it drives shadup's new CLI)."""

from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys

import pytest
from pathlib import Path

INGEST_PY = Path(__file__).resolve().parent.parent / "ingest.py"


def _load_ingest_module():
    spec = importlib.util.spec_from_file_location("ingest_mod", INGEST_PY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


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


def test_ingest_preflight_fails_when_data_not_writable(tmp_path: Path) -> None:
    """Refuse to copy sources when data/ is not writable."""
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)
    data_dir.chmod(0o555)

    src_dir = tmp_path / "album"
    src_dir.mkdir()
    src_file = src_dir / "track.txt"
    src_file.write_bytes(b"content\n")

    env = {
        **os.environ,
        "SHASRV_STORE_ROOT": str(store_root),
        "SHASRV_DB": str(db_path),
    }
    proc = subprocess.run(
        [sys.executable, str(INGEST_PY), str(src_dir)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env=env,
    )

    assert proc.returncode == 1
    assert "cannot write to data/" in proc.stderr
    assert src_file.exists(), "source must be untouched when preflight fails"
    assert not any(files_dir.iterdir()), "files/ must stay empty when preflight fails"


def test_verify_ingested_requires_matching_payload_and_link(tmp_path: Path) -> None:
    ingest = _load_ingest_module()
    store_root, data_dir, files_dir, _db = _layout(tmp_path)
    ingest.STORE_ROOT = store_root
    ingest.DATA_DIR = data_dir
    ingest.FILES_DIR = files_dir

    content = b"verify-me\n"
    digest = _sha256(content)
    payload = _payload_path(data_dir, digest)
    payload.parent.mkdir(parents=True, exist_ok=True)
    payload.write_bytes(content)

    src = tmp_path / "src" / "track.txt"
    src.parent.mkdir(parents=True)
    src.write_bytes(content)
    link = files_dir / "album" / "track.txt"
    link.parent.mkdir(parents=True)
    os.symlink(os.path.relpath(payload, link.parent), link)

    ingest.verify_ingested(src, link)

    wrong_payload = _payload_path(data_dir, _sha256(b"other\n"))
    wrong_payload.parent.mkdir(parents=True, exist_ok=True)
    wrong_payload.write_bytes(b"other\n")
    bad_link = files_dir / "album" / "bad.txt"
    os.symlink(os.path.relpath(wrong_payload, bad_link.parent), bad_link)
    with pytest.raises(RuntimeError, match="does not point at payload"):
        ingest.verify_ingested(src, bad_link)


def test_source_not_removed_when_payload_missing(tmp_path: Path) -> None:
    ingest = _load_ingest_module()
    store_root, data_dir, files_dir, _db = _layout(tmp_path)
    ingest.STORE_ROOT = store_root
    ingest.DATA_DIR = data_dir
    ingest.FILES_DIR = files_dir

    src = tmp_path / "src" / "track.txt"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"orphan source\n")
    link = files_dir / "album" / "track.txt"
    link.parent.mkdir(parents=True)
    os.symlink("../../data/00/" + "0" * 64, link)

    with pytest.raises(RuntimeError, match="payload missing"):
        ingest.remove_source_if_verified(src, link)
    assert src.exists()


def test_ingest_skips_sfv_nfo_and_url_extensions(tmp_path: Path) -> None:
    """Release .sfv/.nfo/.url extensions are skipped (not shadup dotfile rules)."""
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)

    src_dir = tmp_path / "album"
    src_dir.mkdir()
    track = src_dir / "01.flac"
    track.write_bytes(b"audio\n")
    sfv_dot = src_dir / ".sfv"
    sfv_named = src_dir / "album.sfv"
    nfo = src_dir / "release.nfo"
    url = src_dir / "folder.url"
    sfv_dot.write_bytes(b"checksums\n")
    sfv_named.write_bytes(b"checksums\n")
    nfo.write_bytes(b"metadata\n")
    url.write_bytes(b"[InternetShortcut]\n")
    (src_dir / "UPPER.NFO").write_bytes(b"meta\n")
    (src_dir / "Album.SFV").write_bytes(b"sums\n")
    (src_dir / "Folder.URL").write_bytes(b"[InternetShortcut]\n")
    digest = _sha256(b"audio\n")

    _run_ingest(tmp_path, store_root, db_path, [src_dir])
    _assert_stored_symlink(files_dir / "album" / "01.flac", data_dir, digest)
    assert not track.exists()
    assert sfv_dot.exists()
    assert sfv_named.exists()
    assert nfo.exists()
    assert url.exists()
    assert (src_dir / "UPPER.NFO").exists()
    assert (src_dir / "Album.SFV").exists()
    assert (src_dir / "Folder.URL").exists()
    assert not (files_dir / "album" / ".sfv").exists()
    assert not (files_dir / "album" / "album.sfv").exists()
    assert not (files_dir / "album" / "release.nfo").exists()
    assert not (files_dir / "album" / "folder.url").exists()


def test_has_skipped_extension_case_insensitive() -> None:
    ingest = _load_ingest_module()
    assert ingest.has_skipped_extension(Path(".sfv"))
    assert ingest.has_skipped_extension(Path(".SFV"))
    assert ingest.has_skipped_extension(Path("release.nfo"))
    assert ingest.has_skipped_extension(Path("RELEASE.NFO"))
    assert ingest.has_skipped_extension(Path("folder.url"))
    assert ingest.has_skipped_extension(Path("Folder.URL"))
    assert ingest.has_skipped_extension(Path("album.sfv"))
    assert ingest.has_skipped_extension(Path("Album.SFV"))
    assert not ingest.has_skipped_extension(Path("readme.txt"))
    assert ingest.file_extension_lower(Path("Album.SFV")) == ".sfv"


def test_should_skip_ingest_appledouble_glob() -> None:
    ingest = _load_ingest_module()
    assert ingest.should_skip_ingest(Path("._folder.jpg"))
    assert ingest.should_skip_ingest(Path("._01 - track.flac"))
    assert ingest.should_skip_ingest(Path("sub/._foo"))
    assert not ingest.should_skip_ingest(Path(".hidden"))
    assert not ingest.should_skip_ingest(Path("not_appledouble.txt"))


def test_ingest_skips_appledouble_files(tmp_path: Path) -> None:
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)

    src_dir = tmp_path / "album"
    src_dir.mkdir()
    track = src_dir / "01.flac"
    track.write_bytes(b"audio\n")
    appledouble = src_dir / "._01.flac"
    appledouble.write_bytes(b"resource fork\n")
    digest = _sha256(b"audio\n")

    _run_ingest(tmp_path, store_root, db_path, [src_dir])
    _assert_stored_symlink(files_dir / "album" / "01.flac", data_dir, digest)
    assert not track.exists()
    assert appledouble.exists()
    assert not (files_dir / "album" / "._01.flac").exists()


def test_preflight_chmods_readonly_source_dirs(tmp_path: Path) -> None:
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)

    src_dir = tmp_path / "album"
    sub = src_dir / "sub"
    sub.mkdir(parents=True)
    track = sub / "track.txt"
    track.write_bytes(b"content\n")
    sub.chmod(0o555)
    digest = _sha256(b"content\n")

    _run_ingest(tmp_path, store_root, db_path, [src_dir])

    _assert_stored_symlink(files_dir / "album" / "sub" / "track.txt", data_dir, digest)
    assert not track.exists()
    assert not src_dir.exists()


def test_preflight_fails_when_source_dirs_stay_readonly(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    ingest = _load_ingest_module()
    src_dir = tmp_path / "album"
    src_dir.mkdir()
    blocked = [src_dir]

    monkeypatch.setattr(ingest, "removal_blocked_dirs", lambda root: list(blocked))
    monkeypatch.setattr(ingest, "_chmod_dirs_writable", lambda dirs: list(dirs))
    monkeypatch.setattr(
        ingest,
        "_sudo_chmod_dirs_writable",
        lambda root: (_ for _ in ()).throw(subprocess.CalledProcessError(1, "sudo")),
    )

    with pytest.raises(SystemExit):
        ingest.ensure_source_removable(src_dir)
    assert "cannot chmod source tree" in capsys.readouterr().err


def test_idempotent_reingest_removes_leftover_sources(tmp_path: Path) -> None:
    """When store layout already matches, re-ingest only deletes sources."""
    store_root, data_dir, files_dir, db_path = _layout(tmp_path)

    src_dir = tmp_path / "album"
    src_dir.mkdir()
    track = src_dir / "track.txt"
    track.write_bytes(b"same content\n")
    digest = _sha256(track.read_bytes())

    _run_ingest(tmp_path, store_root, db_path, [src_dir])
    assert not track.exists()
    assert not src_dir.exists(), "ingest should prune empty album dir"

    src_dir.mkdir()
    track.write_bytes(b"same content\n")
    link = files_dir / "album" / "track.txt"
    _assert_stored_symlink(link, data_dir, digest)

    _run_ingest(tmp_path, store_root, db_path, [src_dir])
    assert not track.exists(), "re-ingest should remove verified leftover source"
    assert link.is_symlink()
    assert _sha256(link.resolve().read_bytes()) == digest
