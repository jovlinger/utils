"""End-to-end coverage for `build-and-write.sh --include-pub-key`.

Two layers:

* Fast checks that do not touch Docker (option-parsing failure modes, help text).
* A slow build that produces a tmp dist image and verifies the bundled pub key
  matches the one we passed in. Skipped if docker / buildx / mtools are missing.

The slow build relies on the BuildKit cache from the previous DMZ image build, so
on a warm host it completes in ~15 s. On a cold host (first run, no cached
layers) it can take several minutes — that is normal for ARMv6 under QEMU.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def test_help_mentions_include_pub_key() -> None:
    """`--help` advertises the new flag so users discover it."""
    res = subprocess.run(
        ["/bin/sh", str(BUILD), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 2, res.stderr
    assert "--include-pub-key" in res.stderr
    assert "twoway" in res.stderr.lower()


def test_missing_pub_key_file_fails_fast(tmp_path: Path) -> None:
    """Bogus --include-pub-key path must fail before any Docker work starts."""
    res = subprocess.run(
        ["/bin/sh", str(BUILD), f"--include-pub-key={tmp_path}/nope.pem"],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert res.returncode == 1, res.stdout + res.stderr
    assert "file not found" in res.stderr


def test_non_pem_pub_key_file_fails_fast(tmp_path: Path) -> None:
    """A file that is not a PEM PUBLIC KEY must be rejected up front."""
    junk = tmp_path / "junk.pem"
    junk.write_text("not a pem at all\n")
    res = subprocess.run(
        ["/bin/sh", str(BUILD), f"--include-pub-key={junk}"],
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
def test_build_bakes_pub_key_into_fat_image(tmp_path: Path) -> None:
    """build-and-write.sh --include-pub-key writes install/zone-pub.pem into dist/dmz.img."""
    keys_dir = tmp_path / "zone"
    subprocess.run(
        [sys.executable, str(GEN_KEYS)],
        env={"THERMO_ZONE_KEYS_DIR": str(keys_dir), "PATH": os.environ.get("PATH", "")},
        check=True,
        timeout=30,
    )
    pub_pem = keys_dir / "pub.pem"
    assert pub_pem.is_file()

    out_img = tmp_path / "dmz-test.img"

    env = os.environ.copy()
    env["DMZ_OUTPUT_IMG"] = str(out_img)

    res = subprocess.run(
        ["/bin/sh", str(BUILD), f"--include-pub-key={pub_pem}"],
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
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout
    assert "ZONE-PUB PEM" in listing.upper() or "zone-pub.pem" in listing.lower(), (
        "install/zone-pub.pem missing from FAT image; mdir output:\n" + listing
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
