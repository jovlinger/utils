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
from typing import Any, Dict, Mapping, Optional

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

# Local subprocess DMZ: short long-poll so twoway's first POST returns quickly (app reads these at import).
_E2E_LOCAL_DMZ_ENV: Dict[str, str] = {
    "LONG_POLL_TIMEOUT_SECS": os.environ.get("E2E_LONG_POLL_TIMEOUT_SECS", "0.5"),
    "LONG_POLL_SLEEP_SECS": os.environ.get("E2E_LONG_POLL_SLEEP_SECS", "0.1"),
}

# Monotonic trace origin (reset per e2e_services setup).
_E2E_TRACE_T0: Optional[float] = None


def _e2e_trace_reset() -> None:
    global _E2E_TRACE_T0
    _E2E_TRACE_T0 = None


def _e2e_trace(msg: str) -> None:
    """Timeline on stderr (visible in pytest output; use ``pytest -s`` to see live)."""
    global _E2E_TRACE_T0
    now = time.monotonic()
    if _E2E_TRACE_T0 is None:
        _E2E_TRACE_T0 = now
    dt = now - _E2E_TRACE_T0
    print(f"[e2e +{dt:7.3f}s] {msg}", file=sys.stderr, flush=True)


def _e2e_dump_local_stderr(services: Mapping[str, Any]) -> None:
    paths = services.get("_e2e_stderr_paths") if isinstance(services, dict) else None
    if not paths:
        return
    _e2e_trace("---- subprocess stderr (local mode; read before teardown) ----")
    for name, path in sorted(paths.items(), key=lambda x: x[0]):
        p = Path(path)
        _e2e_trace(f"--- {name}: {p} ---")
        try:
            data = p.read_bytes()
            sys.stderr.buffer.write(data)
            if data and not data.endswith(b"\n"):
                sys.stderr.buffer.write(b"\n")
        except OSError as exc:
            _e2e_trace(f"(read failed: {exc})")
    for label, proc in sorted(services.items()):
        if label.startswith("_") or not isinstance(proc, subprocess.Popen):
            continue
        _e2e_trace(f"poll {label}={proc.poll()}")


def _e2e_zones_trace(step: str) -> Dict[str, Any]:
    try:
        r = requests.get(f"{DMZ_URL}/zones", timeout=2)
        body = r.json() if r.ok and r.text else {}
        keys = list(body.keys()) if isinstance(body, dict) else []
        _e2e_trace(
            f"{step}: GET {DMZ_URL}/zones -> {r.status_code} keys={keys!r} "
            f"has_{ZONE_NAME}={ZONE_NAME in body if isinstance(body, dict) else False}"
        )
        return body if isinstance(body, dict) else {}
    except requests.RequestException as exc:
        _e2e_trace(f"{step}: GET /zones failed: {exc!r}")
        return {}


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


def _start_dmz(env: dict, stderr: Any) -> subprocess.Popen:
    env = {**os.environ, "PORT": "5001", "ENV": "DOCKERTEST", **env}
    return subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=DMZ_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr,
    )


def _start_onboard(env: dict, stderr: Any) -> subprocess.Popen:
    env = {**os.environ, "PORT": "5002", "ENV": "DOCKERTEST", **env}
    return subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=ONBOARD_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr,
    )


def _twoway_endpoints() -> tuple[str, str, str]:
    readfrom = f"{ONBOARD_URL}/environment"
    dmz_sensors = f"{DMZ_URL}/zone/{ZONE_NAME}/sensors"
    writeto = f"{ONBOARD_URL}/daikin"
    return readfrom, dmz_sensors, writeto


def _start_twoway(env: dict, stderr: Any) -> subprocess.Popen:
    readfrom, dmz_sensors, writeto = _twoway_endpoints()
    env = {
        **os.environ,
        "ENV": "DOCKERTEST",
        **env,
    }
    return subprocess.Popen(
        [sys.executable, "twoway.py", readfrom, dmz_sensors, writeto],
        cwd=ONBOARD_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=stderr,
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
    _e2e_trace_reset()
    if _in_docker_compose():
        _e2e_trace(
            f"fixture: docker_compose DMZ_URL={DMZ_URL} ONBOARD_URL={ONBOARD_URL} ZONE={ZONE_NAME}"
        )
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
            pytest.fail(f"twoway did not push zone '{ZONE_NAME}' to dmz within 20s")
        # Reset onboard command history so each test starts with a clean slate.
        requests.post(f"{ONBOARD_URL}/test/reset", timeout=5)
        yield {}
        return

    _e2e_trace(
        f"fixture: local_subprocess DMZ_URL={DMZ_URL} ONBOARD_URL={ONBOARD_URL} ZONE={ZONE_NAME}"
    )
    twoway_proc: subprocess.Popen | None = None
    err_handles: list[Any] = []
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        priv_path, pub_path = _gen_keys(tmp)
        pub_pem = pub_path.read_text()
        priv_pem = priv_path.read_text()

        dmz_env = {**_E2E_LOCAL_DMZ_ENV, "ZONE_PUBLIC_KEY": pub_pem}
        onboard_env = {"ZONE_PRIVATE_KEY": priv_pem, "ZONE_NAME": ZONE_NAME}

        dmz_err = open(tmp / "dmz.stderr.log", "wb", buffering=0)
        onboard_err = open(tmp / "onboard.stderr.log", "wb", buffering=0)
        twoway_err = open(tmp / "twoway.stderr.log", "wb", buffering=0)
        err_handles.extend([dmz_err, onboard_err, twoway_err])

        dmz_proc = _start_dmz(dmz_env, stderr=dmz_err)
        onboard_proc = _start_onboard(onboard_env, stderr=onboard_err)
        stderr_paths = {
            "dmz": tmp / "dmz.stderr.log",
            "onboard": tmp / "onboard.stderr.log",
            "twoway": tmp / "twoway.stderr.log",
        }
        try:
            if not _wait_for(f"{DMZ_URL}/zones", timeout=5):
                dmz_proc.terminate()
                onboard_proc.terminate()
                pytest.fail("dmz did not start")
            _e2e_trace("fixture: dmz /zones reachable")
            if not _wait_for(f"{ONBOARD_URL}/help", timeout=5):
                dmz_proc.terminate()
                onboard_proc.terminate()
                pytest.fail("onboard did not start")
            _e2e_trace("fixture: onboard /help reachable")

            rf, dmz_post, wt = _twoway_endpoints()
            _e2e_trace(f"fixture: starting twoway poll={rf!r} post={dmz_post!r} writeto={wt!r}")

            twoway_proc = _start_twoway(onboard_env, stderr=twoway_err)
            time.sleep(0.5)  # let twoway start
            _e2e_trace(f"fixture: twoway started pid={twoway_proc.pid}")

            yield {
                "dmz": dmz_proc,
                "onboard": onboard_proc,
                "twoway": twoway_proc,
                "_e2e_stderr_paths": stderr_paths,
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
            for fh in err_handles:
                try:
                    fh.close()
                except OSError:
                    pass


def test_e2e_sensors_and_commands(e2e_services):
    """Inject fake readings, wait for twoway sync, read from dmz. Send command, verify in onboard."""
    try:
        _e2e_trace("test: POST dmz /test_reset")
        r = requests.post(f"{DMZ_URL}/test_reset", json={"commands": {}, "sensors": {}})
        _e2e_trace(f"test: /test_reset -> {r.status_code}")
        assert r.status_code == 200
        _e2e_trace("test: POST onboard /test/reset")
        r = requests.post(f"{ONBOARD_URL}/test/reset")
        _e2e_trace(f"test: onboard /test/reset -> {r.status_code}")
        assert r.status_code == 200

        _e2e_zones_trace("test: after resets")

        # Inject fake sensor readings on onboard
        _e2e_trace("test: POST onboard /test/inject_readings (19.5C, 55%)")
        r = requests.post(
            f"{ONBOARD_URL}/test/inject_readings",
            json={"temp_centigrade": 19.5, "humid_percent": 55.0},
        )
        _e2e_trace(f"test: inject_readings -> {r.status_code} body[:200]={r.text[:200]!r}")
        assert r.status_code == 200

        # Wait for twoway to poll and push to dmz (DOCKERTEST uses 0.1s interval)
        for i in range(10):
            time.sleep(0.1)
            _e2e_zones_trace(f"test: wait_{i + 1}/10 (+{(i + 1) * 0.1:.1f}s after inject)")

        # Read zones from dmz - should see our sensor data
        _e2e_trace("test: final GET /zones before assert")
        r = requests.get(f"{DMZ_URL}/zones")
        _e2e_trace(f"test: final /zones -> {r.status_code} raw[:500]={r.text[:500]!r}")
        assert r.status_code == 200
        zones = r.json()
        assert ZONE_NAME in zones
        assert zones[ZONE_NAME]["sensors"]["temp_centigrade"] == 19.5
        assert zones[ZONE_NAME]["sensors"]["humid_percent"] == 55.0

        # Send command via dmz
        _e2e_trace("test: POST dmz /zone/.../command")
        r = requests.post(
            f"{DMZ_URL}/zone/{ZONE_NAME}/command",
            json={"power": True, "mode": "HEAT", "temp_c": 22},
        )
        _e2e_trace(f"test: command -> {r.status_code}")
        assert r.status_code == 200

        # Wait for twoway to poll and push command to onboard
        time.sleep(1.0)

        # Read commands from onboard /daikin
        _e2e_trace("test: GET onboard /daikin")
        r = requests.get(f"{ONBOARD_URL}/daikin")
        _e2e_trace(f"test: /daikin -> {r.status_code}")
        assert r.status_code == 200
        cmds = r.json()
        assert len(cmds) >= 1
        # Most recent command should be heat_22 -> power=True, mode=HEAT, temp 22
        latest = cmds[0]["command"]
        assert latest.get("power") is True
        assert latest.get("mode") == "HEAT"
        assert latest.get("half_c") == 44  # 22 * 2
    except AssertionError:
        _e2e_dump_local_stderr(e2e_services)
        raise


def test_e2e_partial_command_merged_on_onboard(e2e_services):
    """Partial DMZ command merges on onboard; DMZ stores only what was last posted to it.

    Convergence model (post-fixup-removal): each side gates command writes on a
    strictly-newer ``created_dt``. Onboard merges a partial DMZ command onto its last
    applied State (so the IR / UI never regresses on missing fields). DMZ stores the
    incoming command verbatim -- it does NOT receive the merged version back, because
    onboard preserves the incoming ``created_dt`` so the round-trip looks "same age"
    and DMZ ignores it. Net effect: hardware state is correct (onboard merged); DMZ
    UI shows the partial command the user last sent (which is what they sent).
    """
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
    # DMZ holds the most recent partial command verbatim -- merging is onboard-only now.
    r = requests.get(f"{DMZ_URL}/zones")
    assert r.status_code == 200
    zcmd = r.json()[ZONE_NAME]["command"]
    assert zcmd.get("fan") == "F3"
    assert zcmd.get("mode") is None  # only "fan: F3" was POSTed last; no merge on DMZ


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
    r = requests.post(
        f"{DMZ_URL}/zone/{ZONE_NAME}/command",
        json={"power": True, "mode": "HEAT", "temp_c": 22},
    )
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
