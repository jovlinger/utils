"""Integration: DMZ ``ui_server`` GET ``/`` vs Flask OAuth (subprocess stack)."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parent / "dmz_ui_stack_runner.py"


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _h, p = s.getsockname()
    s.close()
    return int(p)


def _run_stack(mode: str) -> dict[str, object]:
    fp, up = _free_port(), _free_port()
    if fp == up:
        up = _free_port()
    proc = subprocess.run(
        [sys.executable, str(RUNNER), mode, str(fp), str(up)],
        capture_output=True,
        text=True,
        timeout=90,
    )
    lines = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
    last: dict[str, object] = {}
    if lines:
        try:
            last = json.loads(lines[-1])
        except json.JSONDecodeError:
            last = {"parse_error": lines[-1][:200]}
    assert proc.returncode == 0, (
        f"runner exit {proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}\n"
        f"parsed={last}"
    )
    return last


def test_ui_server_get_root_unauthenticated_follows_to_google_idp() -> None:
    """``GET /`` on ui_server (any port): no session → redirect chain ends at Google."""
    data = _run_stack("unauth")
    assert data.get("ok") is True, data


def test_ui_server_get_root_with_flask_session_returns_thermo_html() -> None:
    """``GET /`` on ui_server with Flask session cookie → 200 HTML shell."""
    data = _run_stack("auth")
    assert data.get("ok") is True, data


def test_pi_dmz_log_replica_login_500_when_google_dns_fails() -> None:
    """Reproduce ``/Volumes/PIBOOT/debug/dmz.log``: 401 on ``/ui/context`` then ``GET /login`` → 500.

    Log excerpt: ``NameResolutionError`` / ``gaierror: [Errno -3] Try again`` for
    ``accounts.google.com`` when loading ``/.well-known/openid-configuration``;
    Flask logs ``Exception on /login [GET]`` and returns **500**.
    """
    data = _run_stack("login_dns_fail")
    assert data.get("ok") is True, data
    assert data.get("ui_status") == 302
    assert data.get("login_status") == 500
    assert "/login" in str(data.get("location", ""))
