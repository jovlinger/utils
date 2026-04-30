"""Verify ``docker export`` of the linux/arm/v6 DMZ image matches Pi chroot expectations.

Fails fast if Dockerfile / .dockerignore regressions omit ``/app/start.sh``, ``tini``,
or the musl dynamic linker — typical causes of ``tini: exec /app/start.sh … ENOENT``.
"""

from __future__ import annotations

import subprocess
import tarfile
from io import BytesIO

import pytest

DOCKER_IMAGE = "jovlinger/thermo/dmz:armv6"


def _image_exists(name: str) -> bool:
    r = subprocess.run(
        ["docker", "image", "inspect", name],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return r.returncode == 0


def _docker_running() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"], capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0


def _export_payload() -> bytes:
    cid = subprocess.check_output(
        [
            "docker",
            "create",
            "--platform",
            "linux/arm/v6",
            "--entrypoint",
            "/bin/true",
            DOCKER_IMAGE,
        ],
        text=True,
    ).strip()
    try:
        return subprocess.check_output(["docker", "export", cid])
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True, check=False)


@pytest.mark.skipif(not _docker_running(), reason="docker daemon not reachable")
@pytest.mark.skipif(not _image_exists(DOCKER_IMAGE), reason=f"{DOCKER_IMAGE} not built locally")
def test_armv6_export_contains_paths_used_by_pi_chroot_launch() -> None:
    """Same members Pi needs: ``tini -- /app/start.sh`` plus interpreters for ``#!/bin/sh``."""
    blob = _export_payload()
    with tarfile.open(fileobj=BytesIO(blob), mode="r:*") as tf:
        names = frozenset(
            member.name.removeprefix("./").strip("/") for member in tf.getmembers()
        )

    needed = frozenset(
        {
            "app/start.sh",
            "sbin/tini",
            "bin/sh",
            "bin/busybox",
            "lib/ld-musl-armhf.so.1",
        }
    )
    missing = sorted(needed - names)
    assert not missing, (
        "docker export tarball missing Pi chroot prerequisites; rebuild jovlinger/thermo/dmz:armv6:\n"
        + "\n".join(f"  - {p}" for p in missing)
    )
