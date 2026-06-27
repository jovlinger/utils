#!/usr/bin/env python3
"""Subprocess helper: Flask DMZ + ui_server on two ports; HTTP checks (stdout JSON).

Usage: ``python dmz_ui_stack_runner.py <mode> <flask_port> <ui_port>``

Modes: ``unauth`` | ``auth`` | ``login_dns_fail``
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable


def _install_google_dns_fail_patch() -> None:
    """Force DNS failure for ``accounts.google.com`` (matches Pi ``gaierror: [Errno -3] Try again``)."""
    _real: Callable[..., Any] = socket.getaddrinfo

    def _fake(
        host: Any,
        port: Any,
        family: int = 0,
        type: int = 0,
        proto: int = 0,
        flags: int = 0,
    ) -> Any:
        h = (
            host.decode("utf-8", errors="replace")
            if isinstance(host, bytes)
            else str(host)
        )
        if "accounts.google.com" in h:
            raise socket.gaierror(-3, "Try again")
        return _real(host, port, family, type, proto, flags)

    socket.getaddrinfo = _fake  # type: ignore[method-assign]


def main() -> None:
    mode = sys.argv[1]
    fp = int(sys.argv[2])
    up = int(sys.argv[3])
    root = Path(__file__).resolve().parents[2]
    dmz = root / "dmz"
    onboard = root / "onboard"
    ui_file = root / "ui" / "ui_server.py"

    # ``dmz`` must precede ``onboard`` so ``import app`` resolves to ``thermo/dmz/app.py``.
    for _p in (str(dmz), str(onboard)):
        while _p in sys.path:
            sys.path.remove(_p)
    sys.path.insert(0, str(onboard))
    sys.path.insert(0, str(dmz))

    for k, v in (
        ("PORT", str(fp)),
        ("UI_PORT", str(up)),
        ("THERMO_UI_BACKEND", "dmz"),
        ("ENV", "UI_INTEGRATION"),
        ("GOOGLE_CLIENT_ID", "ci-test.apps.googleusercontent.com"),
        ("GOOGLE_CLIENT_SECRET", "ci-secret"),
        ("SECRET_KEY", "0123456789abcdef0123456789abcdef"),
        ("ALLOWED_EMAIL_PATTERN", r"^integration-test@gmail\.com$"),
        ("THERMO_UI_LOGIN_ORIGIN", f"http://127.0.0.1:{fp}"),
        ("THERMO_UI_PUBLIC_ORIGIN", f"http://127.0.0.1:{up}"),
    ):
        os.environ[k] = v

    if mode == "login_dns_fail":
        _install_google_dns_fail_patch()

    from werkzeug.serving import make_server

    import app as dmz_app

    srv = make_server("127.0.0.1", fp, dmz_app.app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", fp), timeout=0.15).close()
            break
        except OSError:
            time.sleep(0.05)
    else:
        print(json.dumps({"ok": False, "error": "flask_bind_timeout"}), flush=True)
        sys.exit(2)

    spec = importlib.util.spec_from_file_location("ThermoUiServer", str(ui_file))
    uis = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(uis)
    threading.Thread(target=uis.main, daemon=True).start()
    time.sleep(0.9)

    import requests

    if mode == "unauth":
        r = requests.get(
            f"http://127.0.0.1:{up}/",
            headers={"Accept": "text/html,application/xhtml+xml,*/*"},
            allow_redirects=True,
            timeout=25,
        )
        ok = "accounts.google.com" in r.url
        print(
            json.dumps({"ok": ok, "final_url": r.url, "status": r.status_code}),
            flush=True,
        )
        sys.exit(0 if ok else 1)
    if mode == "auth":
        s = requests.Session()
        r0 = s.get(f"http://127.0.0.1:{fp}/test/ui_session", timeout=10)
        if r0.status_code != 200:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "test_ui_session",
                        "status": r0.status_code,
                    }
                ),
                flush=True,
            )
            sys.exit(1)
        r = s.get(
            f"http://127.0.0.1:{up}/",
            headers={"Accept": "text/html,*/*"},
            timeout=15,
        )
        body = r.text or ""
        ok = r.status_code == 200 and (
            "Thermo" in body or "thermo" in body.lower() or "<title>" in body
        )
        print(
            json.dumps({"ok": ok, "status": r.status_code, "len": len(body)}),
            flush=True,
        )
        sys.exit(0 if ok else 1)

    if mode == "login_dns_fail":
        # Same sequence as /Volumes/PIBOOT/debug/dmz.log: ui_server GET /ui/context -> 401,
        # browser follows Location to Flask /login -> OIDC metadata fetch -> DNS EAI_AGAIN -> 500.
        r_ui = requests.get(
            f"http://127.0.0.1:{up}/",
            headers={"Accept": "text/html,*/*"},
            allow_redirects=False,
            timeout=15,
        )
        loc = (r_ui.headers.get("Location") or "").strip()
        login_url = loc
        if loc.startswith("/"):
            login_url = f"http://127.0.0.1:{fp}{loc}"
        r_login = requests.get(login_url, allow_redirects=False, timeout=15)
        ok = r_ui.status_code == 302 and "/login" in loc and r_login.status_code == 500
        body_snip = (r_login.text or "")[:400]
        print(
            json.dumps(
                {
                    "ok": ok,
                    "ui_status": r_ui.status_code,
                    "location": loc,
                    "login_status": r_login.status_code,
                    "login_body_prefix": body_snip,
                }
            ),
            flush=True,
        )
        sys.exit(0 if ok else 1)

    print(json.dumps({"ok": False, "error": "bad_mode"}), flush=True)
    sys.exit(2)


if __name__ == "__main__":
    main()
