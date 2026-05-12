"""Tests for ``build-and-write.sh`` (mandatory zone pub + OAuth on every SD image)."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterator

import pytest

DMZ_DIR = Path(__file__).resolve().parent.parent
THERMO_DIR = DMZ_DIR.parent
GEN_KEYS = THERMO_DIR / "test" / "gen_keys.py"
BUILD = DMZ_DIR / "build-and-write.sh"

pytestmark = pytest.mark.skipif(
    not BUILD.is_file(),
    reason="build-and-write.sh not in tree (e.g. DMZ runtime image lacks SD build scripts)",
)


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _docker_running() -> bool:
    if not _have("docker"):
        return False
    res = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, timeout=15
    )
    return res.returncode == 0


def _write_min_oauth_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "google-client-id").write_text(
        "ci-test-google-client-id-0001\n", encoding="utf-8"
    )
    (path / "google-client-secret").write_text(
        "ci-test-google-client-secret-zz\n", encoding="utf-8"
    )
    (path / "flask-secret-key").write_text(
        "ci0123456789abcdef0123456789abcd\n", encoding="utf-8"
    )
    (path / "allowed-email").write_text(r"^allowed-ci@example\.com$" + "\n", encoding="utf-8")


@contextlib.contextmanager
def _staged_dmz_secrets(tmp_path: Path) -> Iterator[Path]:
    """Temporarily replace ``thermo/dmz/.secrets`` so tests can populate fixed paths."""
    sec = DMZ_DIR / ".secrets"
    backup = tmp_path / "_secrets_tree_backup"
    had = sec.exists()
    if had:
        shutil.move(str(sec), str(backup))
    try:
        yield sec
    finally:
        if sec.exists():
            shutil.rmtree(sec)
        if had and backup.exists():
            shutil.move(str(backup), str(sec))


def test_help_mentions_required_secrets() -> None:
    """``--help`` states that zone + OAuth material is always required."""
    res = subprocess.run(
        ["/bin/sh", str(BUILD), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2, res.stderr
    assert ".secrets/zone/pub.pem" in res.stderr
    assert "allowed-email" in res.stderr or "OAuth" in res.stderr
    assert "No overrides" in res.stderr or "no overrides" in res.stderr.lower()


def test_missing_zone_pub_file_fails_fast(tmp_path: Path) -> None:
    """Missing zone pub PEM must fail before Docker work starts."""
    with _staged_dmz_secrets(tmp_path) as sec:
        (sec / "zone").mkdir(parents=True, exist_ok=True)
        _write_min_oauth_dir(sec / "oauth")
        res = subprocess.run(
            ["/bin/sh", str(BUILD)],
            cwd=str(DMZ_DIR),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    assert res.returncode == 1, res.stdout + res.stderr
    assert "Not found" in res.stderr or "not found" in res.stderr.lower() or "required" in res.stderr.lower()


def test_non_pem_zone_pub_file_fails_fast(tmp_path: Path) -> None:
    """A file that is not a PEM PUBLIC KEY must be rejected up front."""
    with _staged_dmz_secrets(tmp_path) as sec:
        (sec / "zone").mkdir(parents=True, exist_ok=True)
        junk = sec / "zone" / "pub.pem"
        junk.write_text("not a pem at all\n", encoding="utf-8")
        _write_min_oauth_dir(sec / "oauth")
        res = subprocess.run(
            ["/bin/sh", str(BUILD)],
            cwd=str(DMZ_DIR),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    assert res.returncode == 1, res.stdout + res.stderr
    assert "PEM public key" in res.stderr


def test_unknown_flag_rejected() -> None:
    """Option parsing should not silently swallow typos."""
    res = subprocess.run(
        ["/bin/sh", str(BUILD), "--bogus=yes"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert res.returncode == 2
    assert "unrecognized argument" in res.stderr


@pytest.mark.skipif(
    not _have("mcopy") or not _have("mdir"),
    reason="mtools (mcopy/mdir) not installed; skip end-to-end build verification",
)
@pytest.mark.skipif(
    not _docker_running(),
    reason="docker daemon not reachable; skip end-to-end build verification",
)
def test_build_always_bakes_zone_pub_and_oauth_into_fat_image(tmp_path: Path) -> None:
    """Every image includes install/zone-pub.pem and OAuth client files under fixed .secrets paths."""
    with _staged_dmz_secrets(tmp_path) as sec:
        keys_dir = sec / "zone"
        subprocess.run(
            [sys.executable, str(GEN_KEYS)],
            env={
                "THERMO_ZONE_KEYS_DIR": str(keys_dir),
                "PATH": os.environ.get("PATH", ""),
            },
            check=True,
            timeout=30,
        )
        pub_pem = keys_dir / "pub.pem"
        assert pub_pem.is_file()

        oauth_dir = sec / "oauth"
        _write_min_oauth_dir(oauth_dir)
        oauth_id_line = "e2e-oauth-client-id-abcdef.apps.googleusercontent.com\n"
        (oauth_dir / "google-client-id").write_text(oauth_id_line, encoding="utf-8")

        out_img = tmp_path / "dmz-test.img"
        env = os.environ.copy()
        env["DMZ_OUTPUT_IMG"] = str(out_img)

        res = subprocess.run(
            ["/bin/sh", str(BUILD)],
            cwd=str(DMZ_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert res.returncode == 0, (
            f"build-and-write.sh failed (exit {res.returncode})\n"
            f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
        )
        assert out_img.is_file(), "expected output .img not produced"

        listing = subprocess.run(
            ["mdir", "-i", str(out_img), "::install"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        ).stdout
        assert "ZONE-PUB PEM" in listing.upper() or "zone-pub.pem" in listing.lower(), (
            "install/zone-pub.pem missing from FAT image; mdir output:\n" + listing
        )
        assert "google-client-id" in listing.lower(), (
            "install/google-client-id missing from FAT; mdir output:\n" + listing
        )

        extracted = tmp_path / "extracted-pub.pem"
        subprocess.run(
            ["mcopy", "-i", str(out_img), "::install/zone-pub.pem", str(extracted)],
            check=True,
            timeout=15,
        )
        assert extracted.read_bytes() == pub_pem.read_bytes(), (
            "FAT-image pub key bytes differ from source"
        )

        extracted_oauth = tmp_path / "extracted-google-client-id"
        subprocess.run(
            [
                "mcopy",
                "-i",
                str(out_img),
                "::install/google-client-id",
                str(extracted_oauth),
            ],
            check=True,
            timeout=15,
        )
        assert extracted_oauth.read_text(encoding="utf-8") == oauth_id_line

        buildinfo = tmp_path / "buildinfo.txt"
        subprocess.run(
            ["mcopy", "-i", str(out_img), "::install/buildinfo.txt", str(buildinfo)],
            check=True,
            timeout=15,
        )
        info = buildinfo.read_text()
        assert "zone_pub_sha256=" in info and "zone_pub_sha256=none" not in info, (
            "buildinfo.txt should record the zone pub key SHA256, got:\n" + info
        )
        assert "zone_machine_auth=baked" in info, (
            "buildinfo.txt must declare zone_machine_auth=baked:\n" + info
        )
        assert "oauth_client_files=baked" in info, (
            "buildinfo.txt must declare oauth_client_files=baked:\n" + info
        )
