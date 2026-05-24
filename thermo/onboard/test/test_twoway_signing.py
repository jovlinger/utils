"""Loud-on-misconfig smoke tests for twoway zone auth.

Why subprocess and not import: ``twoway.py`` runs configuration + key probing at module
import time (so the loud WARN/ERROR/INFO fires before any polling). Re-importing inside a
single pytest process would leak state across tests, and we want to assert the *startup*
log line — exactly what an operator sees when they `docker logs thermo-onboard-twoway`.

These tests catch the regression from 2026-04-19, where twoway silently shipped with
``signing_enabled=False`` and every DMZ POST 401'd with no client-side hint as to why
(see the thermo/onboard/twoway.py `_probe_signing` docstring).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

_HERE = Path(__file__).resolve().parent
_ONBOARD = _HERE.parent

# Args twoway.py asserts on (URL1 URL2 URL3). Hosts/ports are intentionally unreachable so
# the polling loop never starts a real request — we exit before `poll_forever()` runs by
# raising in a sys.settrace hook (see _RUN_TWOWAY_BOOT below). The DMZ URL contains a
# /zone/<name>/ segment so ZONE_NAME is auto-extracted (mirrors prod URL shape).
_ARGV: List[str] = [
    "twoway.py",
    "http://127.0.0.1:1/environment",
    "http://127.0.0.1:1/zone/testzone/sensors",
    "http://127.0.0.1:1/daikin",
]

# Boot twoway, then exit before poll_forever() can run. ``logger.info("enter")`` is the last log
# line emitted at module top-level before the `if __name__ == "__main__":` guard, so we
# install an audit hook that abort()s right after the module import completes. We avoid
# `if __name__ == "__main__"` by importing twoway as a module (not running it).
_RUN_TWOWAY_BOOT = (
    "import sys, os\n"
    "sys.argv = {argv!r}\n"
    "sys.path.insert(0, {onboard!r})\n"
    "import twoway  # noqa: F401  -- module-import side effects ARE the test\n"
    "sys.exit(0)\n"
)


def _run_twoway(env_overrides: Optional[Dict[str, str]] = None) -> Tuple[str, str, int]:
    """Boot twoway in a subprocess; return (stdout, stderr, returncode).

    Logging goes to stdout via common.configure_logging() -> StreamHandler(sys.stdout).
    """
    env = os.environ.copy()
    env.pop("ZONE_PRIVATE_KEY", None)
    env.pop("ZONE_PRIVATE_KEY_PATH", None)
    env.pop("ZONE_NAME", None)
    env.pop("LOG_PATH", None)
    env["LOG_LEVEL"] = "DEBUG"
    if env_overrides:
        env.update(env_overrides)
    code = _RUN_TWOWAY_BOOT.format(argv=_ARGV, onboard=str(_ONBOARD))
    p = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return p.stdout, p.stderr, p.returncode


def test_no_key_emits_loud_warn_at_startup() -> None:
    """No ZONE_PRIVATE_KEY* env var => WARN line that explicitly names the env var to set.

    This is the regression that silent-401'd us in production: with no key the operator
    saw nothing at startup, then saw 401s and assumed key+sig were broken.
    """
    out, errlog, rc = _run_twoway()
    assert rc == 0, f"twoway boot failed: rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{errlog}"
    log = out + errlog
    assert "WARNING" in log, f"expected WARNING-level log; got:\n{log}"
    assert "zone auth DISABLED" in log, f"expected DISABLED warning; got:\n{log}"
    # The hint must name the env var the operator should set — searching docs is annoying.
    assert "ZONE_PRIVATE_KEY_PATH" in log
    # Negative: no INFO line claiming auth is enabled.
    assert "zone auth ENABLED" not in log


def test_valid_key_emits_enabled_with_fingerprint(tmp_path: Path) -> None:
    """Generated keypair => INFO line with stable 16-hex-char key_sha256 fingerprint.

    Operator can compare this to DMZ's `cat /etc/dmz/zone-pub.pem | ... fingerprint` to
    confirm both sides hold the same keypair without having to copy the key around.
    """
    sys.path.insert(0, str(_ONBOARD))
    from zone_auth import generate_keypair, public_key_fingerprint, _load_private_key

    priv_pem, _pub_pem = generate_keypair()
    priv_path = tmp_path / "priv.pem"
    priv_path.write_bytes(priv_pem)
    expected_fp = public_key_fingerprint(_load_private_key(str(priv_path)))

    out, errlog, rc = _run_twoway({"ZONE_PRIVATE_KEY_PATH": str(priv_path)})
    assert rc == 0, f"twoway boot failed: rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{errlog}"
    log = out + errlog
    assert "zone auth ENABLED" in log, f"expected ENABLED line; got:\n{log}"
    assert (
        f"key_sha256='{expected_fp}'" in log or f"key_sha256={expected_fp}" in log
    ), f"expected key_sha256={expected_fp}; got:\n{log}"
    assert "zone='testzone'" in log or "zone=testzone" in log
    assert "DISABLED" not in log
    assert "MISCONFIGURED" not in log


def test_missing_key_file_emits_loud_error(tmp_path: Path) -> None:
    """ZONE_PRIVATE_KEY_PATH points at a nonexistent file => ERROR (not WARN).

    Different severity from "no key configured" because this one IS a config bug — the
    operator clearly intended to enable auth.
    """
    bogus = tmp_path / "does-not-exist.pem"
    out, errlog, rc = _run_twoway({"ZONE_PRIVATE_KEY_PATH": str(bogus)})
    assert rc == 0, f"twoway boot failed: rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{errlog}"
    log = out + errlog
    assert "ERROR" in log
    assert "MISCONFIGURED" in log
    assert "private key file not found" in log
    assert "zone auth ENABLED" not in log


def test_garbage_key_emits_loud_error(tmp_path: Path) -> None:
    """Existing-but-invalid key file => ERROR (not WARN). Names the loader's exception.

    Catches accidentally bind-mounting the wrong file (e.g. .pub instead of priv.pem,
    or an OpenSSH-format key we do not support).
    """
    junk = tmp_path / "junk.pem"
    junk.write_text("this is not a key\n")
    out, errlog, rc = _run_twoway({"ZONE_PRIVATE_KEY_PATH": str(junk)})
    assert rc == 0, f"twoway boot failed: rc={rc}\nSTDOUT:\n{out}\nSTDERR:\n{errlog}"
    log = out + errlog
    assert "ERROR" in log
    assert "MISCONFIGURED" in log
    assert "failed to load Ed25519 private key" in log
    assert "zone auth ENABLED" not in log


@pytest.mark.parametrize(
    "case_label, key_present, expected_signing_enabled_field",
    [
        ("no_key", False, "signing_enabled=False"),
        ("good_key", True, "signing_enabled=True"),
    ],
)
def test_config_summary_reflects_signing_state(
    tmp_path: Path,
    case_label: str,
    key_present: bool,
    expected_signing_enabled_field: str,
) -> None:
    """The single 'twoway config' INFO line must show signing_enabled in {True, False},
    matching the probe outcome — so an operator scanning startup logs sees the truth in
    one place even if they miss the WARN/INFO lines emitted by _probe_signing."""
    overrides: Dict[str, str] = {}
    if key_present:
        sys.path.insert(0, str(_ONBOARD))
        from zone_auth import generate_keypair

        priv_pem, _ = generate_keypair()
        priv_path = tmp_path / "priv.pem"
        priv_path.write_bytes(priv_pem)
        overrides["ZONE_PRIVATE_KEY_PATH"] = str(priv_path)
    out, errlog, rc = _run_twoway(overrides)
    assert rc == 0, f"[{case_label}] twoway boot failed:\nSTDOUT:\n{out}\nSTDERR:\n{errlog}"
    log = out + errlog
    assert "twoway config" in log
    assert expected_signing_enabled_field in log, (
        f"[{case_label}] expected '{expected_signing_enabled_field}' in config line; got:\n{log}"
    )
