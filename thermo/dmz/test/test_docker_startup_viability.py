"""Verify the production DMZ image starts through its default entrypoint."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

DMZ_DIR = Path(__file__).resolve().parent.parent
STARTUP_SCRIPT = DMZ_DIR / "test" / "docker-startup-viability.sh"
DOCKER_IMAGE = os.environ.get("DMZ_DOCKER_IMAGE", "jovlinger/thermo/dmz:armv6")


def _have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def _docker_running() -> bool:
    if not _have("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def _image_exists(name: str) -> bool:
    if not _have("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "image", "inspect", name],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


@pytest.mark.skipif(not _docker_running(), reason="docker daemon not reachable")
@pytest.mark.skipif(not _image_exists(DOCKER_IMAGE), reason=f"{DOCKER_IMAGE} not built locally")
def test_armv6_image_default_entrypoint_reaches_diagnostics() -> None:
    """The image must survive ``tini -- /app/start.sh`` and serve diagnostics."""
    env = os.environ.copy()
    env.setdefault("DMZ_DOCKER_IMAGE", DOCKER_IMAGE)
    env.setdefault("DMZ_DOCKER_PLATFORM", "linux/arm/v6")
    timeout_seconds = int(env.get("DMZ_STARTUP_TIMEOUT", "90"))

    res = subprocess.run(
        ["/bin/sh", str(STARTUP_SCRIPT)],
        cwd=str(DMZ_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_seconds + 30,
        check=False,
    )
    assert res.returncode == 0, (
        f"DMZ image failed default-entrypoint startup check (exit {res.returncode})\n"
        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
    )
