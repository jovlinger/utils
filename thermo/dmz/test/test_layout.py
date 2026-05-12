"""Sanity checks for container layout (no Docker required)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def dmz_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def test_start_sh_invokes_su_exec_and_run_sh(dmz_dir: Path) -> None:
    p = dmz_dir / "start.sh"
    assert p.is_file(), f"Missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "su-exec dmz" in text
    assert "/app/run.sh" in text


def test_dockerfile_non_root_and_entrypoint(dmz_dir: Path) -> None:
    p = dmz_dir / "Dockerfile"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "adduser" in text
    assert "su-exec" in text
    assert "start.sh" in text
    assert "8080" in text
    assert ".docker-import/run-with-stdout-logged.py" in text


def test_dmz_boot_brings_loopback_up(dmz_dir: Path) -> None:
    """Loopback must be configured before eth0; without 127.0.0.1 the bundled UI
    server (chroot-local urlopen to ``http://127.0.0.1:5000``) hangs at SYN.

    Pi 1B image bypasses Alpine's ``networking`` openrc service, so nothing else
    in the boot path will bring ``lo`` up if this is removed.
    """
    p = dmz_dir / "install" / "dmz-boot.start"
    if not p.is_file():
        pytest.skip("install/ not shipped in slim runtime image")
    text = p.read_text(encoding="utf-8")
    assert "ip link set lo up" in text, "dmz-boot.start no longer brings lo up"
    assert "ip addr add 127.0.0.1/8 dev lo" in text, (
        "dmz-boot.start no longer assigns 127.0.0.1/8 to lo"
    )
    lo_idx = text.index("ip link set lo up")
    eth0_idx = text.index("ip link set eth0 up")
    assert lo_idx < eth0_idx, (
        "lo bringup must precede eth0 bringup so localhost works during eth0 wait"
    )


def test_rescue_script_brings_loopback_up(dmz_dir: Path) -> None:
    """Rescue path is sometimes invoked before dmz-boot.start has run; it must
    also be self-sufficient about loopback (idempotent: ``2>/dev/null || true``).
    """
    p = dmz_dir / "install" / "sshd.sh"
    if not p.is_file():
        pytest.skip("install/ not shipped in slim runtime image")
    text = p.read_text(encoding="utf-8")
    assert "ip link set lo up" in text, "rescue script no longer brings lo up"
    assert "ip addr add 127.0.0.1/8 dev lo" in text, (
        "rescue script no longer assigns 127.0.0.1/8 to lo"
    )
