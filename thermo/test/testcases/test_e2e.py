"""
E2E test: onboard + twoway + dmz with Ed25519 machine auth.

Composes all three components. Onboard provides fake sensor readings;
twoway syncs to dmz (signed) and back to onboard. Testdriver pokes dmz
to read sensors and send commands, then verifies commands appear in onboard.

Docker images (must match ``thermo/test/docker-compose.yml`` and ``thermo/onboard/Makefile``):

- ``THERMO_ONBOARD_IMAGE`` — Flask + UI (``Dockerfile.onboard``).
- ``THERMO_ONBOARD_TWOWAY_IMAGE`` — twoway sync (``Dockerfile.twoway``).

Build locally before compose: from ``thermo/onboard`` run ``make images`` (or ``make test_e2e``
from ``thermo/test``, which invokes that). Push to GHCR: ``make push_images`` (needs ``CR_PAT``).

Registry: images are pushed to **GHCR** under ``ghcr.io/jovlinger/…`` (same as CI:
``.github/workflows/thermo-onboard.yml``). To confirm the namespaces exist without logging in,
``curl -sI https://ghcr.io/v2/jovlinger/thermo-onboard-app/manifests/latest`` returns **401**
with a ``WWW-Authenticate`` scope (anonymous pull is denied but the repository is registered).

Runs in two modes:
- Local: subprocess starts dmz, onboard, twoway (DMZ_URL/ONBOARD_URL from env or localhost)
- Docker: dmz and onboard are containers; use DMZ_URL=http://dmz:8080 etc.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest
import requests

# Add thermo paths for imports
THERMO = Path(__file__).resolve().parent.parent.parent
DMZ_DIR = THERMO / "dmz"
ONBOARD_DIR = THERMO / "onboard"
sys.path.insert(0, str(DMZ_DIR))

# Pinned to GHCR / Makefile IMAGE_APP and IMAGE_TWOWAY (default tag latest).
THERMO_ONBOARD_IMAGE = "ghcr.io/jovlinger/thermo-onboard-app"
THERMO_ONBOARD_TWOWAY_IMAGE = "ghcr.io/jovlinger/thermo-onboard-twoway"
DEFAULT_IMAGE_TAG = "latest"

DMZ_URL = os.environ.get("DMZ_URL", "http://127.0.0.1:5001")
ONBOARD_URL = os.environ.get("ONBOARD_URL", "http://127.0.0.1:5002")
ZONE_NAME = os.environ.get("E2E_ZONE_NAME", "e2ezone")


def _in_docker_compose() -> bool:
    """True when running e2e against docker-compose service hostnames."""
    return "://dmz:" in DMZ_URL and "://onboard:" in ONBOARD_URL


def _gen_keys(tmpdir: Path) -> tuple[Path, Path]:
    """Generate Ed25519 keypair; return (priv_path, pub_path)."""
    from zone_auth import generate_keypair

    priv_pem, pub_pem = generate_keypair()
    priv_path = tmpdir / "priv.pem"
    pub_path = tmpdir / "pub.pem"
    priv_path.write_bytes(priv_pem)
    pub_path.write_bytes(pub_pem)
    return priv_path, pub_path


def _start_dmz(env: dict) -> subprocess.Popen:
    env = {**os.environ, "PORT": "5001", "ENV": "DOCKERTEST", **env}
    return subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=DMZ_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _start_onboard(env: dict) -> subprocess.Popen:
    env = {**os.environ, "PORT": "5002", "ENV": "DOCKERTEST", **env}
    return subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=ONBOARD_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _start_twoway(env: dict) -> subprocess.Popen:
    readfrom = f"{ONBOARD_URL}/environment"
    dmz = f"{DMZ_URL}/zone/{ZONE_NAME}/sensors"
    writeto = f"{ONBOARD_URL}/daikin"
    env = {
        **os.environ,
        "ENV": "DOCKERTEST",
        **env,
    }
    return subprocess.Popen(
        [sys.executable, "twoway.py", readfrom, dmz, writeto],
        cwd=ONBOARD_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait_for(url: str, timeout: float = 10.0) -> bool:
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=1)
            if r.ok:
                return True
        except requests.RequestException:
            pass
        time.sleep(0.1)
    return False


@pytest.fixture
def e2e_services():
    """Local: start dmz, onboard, twoway with temp keys. Compose: use deployed stack (HTTP only)."""
    if _in_docker_compose():
        if not _wait_for(f"{DMZ_URL}/zones", timeout=30):
            pytest.fail("dmz did not start (docker-compose)")
        if not _wait_for(f"{ONBOARD_URL}/help", timeout=30):
            pytest.fail("onboard did not start (docker-compose)")
        # Warm up twoway: inject a probe reading, then wait for it to appear in
        # DMZ. This confirms twoway has completed at least one full poll cycle
        # before the test body resets DMZ and injects its own readings.
        requests.post(
            f"{ONBOARD_URL}/test/inject_readings",
            json={"temp_centigrade": -99.0},
            timeout=5,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                r = requests.get(f"{DMZ_URL}/zones", timeout=2)
                if r.ok and ZONE_NAME in r.json():
                    break
            except requests.RequestException:
                pass
            time.sleep(0.2)
        else:
            pytest.fail(
                f"twoway did not push zone '{ZONE_NAME}' to dmz within 20s"
            )
        # Reset onboard command history so each test starts with a clean slate.
        requests.post(f"{ONBOARD_URL}/test/reset", timeout=5)
        yield {}
        return

    twoway_proc: subprocess.Popen | None = None
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        priv_path, pub_path = _gen_keys(tmp)
        pub_pem = pub_path.read_text()
        priv_pem = priv_path.read_text()

        dmz_env = {"ZONE_PUBLIC_KEY": pub_pem}
        onboard_env = {"ZONE_PRIVATE_KEY": priv_pem, "ZONE_NAME": ZONE_NAME}

        dmz_proc = _start_dmz(dmz_env)
        onboard_proc = _start_onboard(onboard_env)
        try:
            if not _wait_for(f"{DMZ_URL}/zones", timeout=5):
                dmz_proc.terminate()
                onboard_proc.terminate()
                pytest.fail("dmz did not start")
            if not _wait_for(f"{ONBOARD_URL}/help", timeout=5):
                dmz_proc.terminate()
                onboard_proc.terminate()
                pytest.fail("onboard did not start")

            twoway_proc = _start_twoway(onboard_env)
            time.sleep(0.5)  # let twoway start

            yield {
                "dmz": dmz_proc,
                "onboard": onboard_proc,
                "twoway": twoway_proc,
            }
        finally:
            if twoway_proc is not None:
                twoway_proc.terminate()
            onboard_proc.terminate()
            dmz_proc.terminate()
            procs = [p for p in (twoway_proc, onboard_proc, dmz_proc) if p is not None]
            for p in procs:
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    p.kill()


def test_e2e_sensors_and_commands(e2e_services):
    """Inject fake readings, wait for twoway sync, read from dmz. Send command, verify in onboard."""
    r = requests.post(f"{DMZ_URL}/test_reset", json={"commands": {}, "sensors": {}})
    assert r.status_code == 200
    r = requests.post(f"{ONBOARD_URL}/test/reset")
    assert r.status_code == 200

    # Inject fake sensor readings on onboard
    r = requests.post(
        f"{ONBOARD_URL}/test/inject_readings",
        json={"temp_centigrade": 19.5, "humid_percent": 55.0},
    )
    assert r.status_code == 200

    # Wait for twoway to poll and push to dmz (DOCKERTEST uses 0.1s interval)
    time.sleep(1.0)

    # Read zones from dmz - should see our sensor data
    r = requests.get(f"{DMZ_URL}/zones")
    assert r.status_code == 200
    zones = r.json()
    assert ZONE_NAME in zones
    assert zones[ZONE_NAME]["sensors"]["temp_centigrade"] == 19.5
    assert zones[ZONE_NAME]["sensors"]["humid_percent"] == 55.0

    # Send command via dmz
    r = requests.post(
        f"{DMZ_URL}/zone/{ZONE_NAME}/command",
        json={"power": True, "mode": "HEAT", "temp_c": 22},
    )
    assert r.status_code == 200

    # Wait for twoway to poll and push command to onboard
    time.sleep(1.0)

    # Read commands from onboard /daikin
    r = requests.get(f"{ONBOARD_URL}/daikin")
    assert r.status_code == 200
    cmds = r.json()
    assert len(cmds) >= 1
    # Most recent command should be heat_22 -> power=True, mode=HEAT, temp 22
    latest = cmds[0]["command"]
    assert latest.get("power") is True
    assert latest.get("mode") == "HEAT"
    assert latest.get("half_c") == 44  # 22 * 2


def test_e2e_partial_command_merged_and_pushed_to_dmz(e2e_services):
    """Partial DMZ command merges on onboard; twoway pushes full command back so DMZ stays consistent."""
    r = requests.post(f"{DMZ_URL}/test_reset", json={"commands": {}, "sensors": {}})
    assert r.status_code == 200
    r = requests.post(f"{ONBOARD_URL}/test/reset")
    assert r.status_code == 200
    r = requests.post(
        f"{ONBOARD_URL}/test/inject_readings",
        json={"temp_centigrade": 19.5, "humid_percent": 55.0},
    )
    assert r.status_code == 200
    time.sleep(1.0)
    r = requests.post(
        f"{DMZ_URL}/zone/{ZONE_NAME}/command",
        json={"power": True, "mode": "HEAT", "temp_c": 22},
    )
    assert r.status_code == 200
    time.sleep(1.0)
    r = requests.post(
        f"{DMZ_URL}/zone/{ZONE_NAME}/command",
        json={"fan": "F3"},
    )
    assert r.status_code == 200
    time.sleep(1.2)
    r = requests.get(f"{ONBOARD_URL}/daikin")
    assert r.status_code == 200
    latest = r.json()[0]["command"]
    assert latest.get("mode") == "HEAT"
    assert latest.get("fan") == "F3"
    r = requests.get(f"{DMZ_URL}/zones")
    assert r.status_code == 200
    zcmd = r.json()[ZONE_NAME]["command"]
    assert zcmd.get("mode") == "HEAT"
    assert zcmd.get("fan") == "F3"


def test_e2e_docker_compose():
    """
    E2E against docker-compose services (dmz, onboard with twoway).
    Set DMZ_URL=http://dmz:8080 ONBOARD_URL=http://onboard:5000 E2E_ZONE_NAME=zoneymczoneface.
    """
    if "dmz" not in DMZ_URL:
        pytest.skip("run with DMZ_URL=http://dmz:8080 (docker-compose)")
    if not _wait_for(f"{DMZ_URL}/zones", timeout=15):
        pytest.fail("dmz did not start (docker-compose)")
    if not _wait_for(f"{ONBOARD_URL}/help", timeout=15):
        pytest.fail("onboard did not start (docker-compose)")
    # Reset dmz
    r = requests.post(f"{DMZ_URL}/test_reset", json={"commands": {}, "sensors": {}})
    assert r.status_code == 200
    # Inject fake readings
    r = requests.post(
        f"{ONBOARD_URL}/test/inject_readings",
        json={"temp_centigrade": 19.5, "humid_percent": 55.0},
    )
    assert r.status_code == 200
    time.sleep(1.5)
    # Read zones
    r = requests.get(f"{DMZ_URL}/zones")
    assert r.status_code == 200
    zones = r.json()
    assert ZONE_NAME in zones
    assert zones[ZONE_NAME]["sensors"]["temp_centigrade"] == 19.5
    # Send command
    r = requests.post(f"{DMZ_URL}/zone/{ZONE_NAME}/command", json={"power": True, "mode": "HEAT", "temp_c": 22})
    assert r.status_code == 200
    time.sleep(1.5)
    # Verify command in onboard
    r = requests.get(f"{ONBOARD_URL}/daikin")
    assert r.status_code == 200
    cmds = r.json()
    assert len(cmds) >= 1
    latest = cmds[0]["command"]
    assert latest.get("power") is True
    assert latest.get("mode") == "HEAT"
