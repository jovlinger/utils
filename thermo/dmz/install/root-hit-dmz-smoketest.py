#!/usr/bin/env python3
"""
DMZ smoketest for Pi 1B.

Purpose:
  - hit DMZ `app.py` endpoints on both :80 (iptables redirect) and :8080
  - post canned "twoway-like" fake environment -> /zone/<zone>/sensors
  - print key responses so you can see whether the app is alive

Runs on the Pi inside the DMZ image as /root/dmz-smoketest.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def _log(msg: str) -> None:
    print(msg, flush=True)


def _url(base: str, path: str) -> str:
    if base.endswith("/") and path.startswith("/"):
        return base[:-1] + path
    if not base.endswith("/") and not path.startswith("/"):
        return base + "/" + path
    return base + path


def _http_json(
    method: str,
    url: str,
    body: Optional[Dict[str, Any]] = None,
    timeout_sec: float = 5.0,
) -> Tuple[int, str, Optional[Any]]:
    data: Optional[bytes] = None
    headers: Dict[str, str] = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as r:
            text = r.read().decode("utf-8", errors="replace")
            try:
                return r.status, text, json.loads(text) if text else None
            except Exception:
                return r.status, text, None
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace") if e.fp is not None else ""
        try:
            return e.code, text, json.loads(text) if text else None
        except Exception:
            return e.code, text, None


def _hit_sequence(base: str, zone: str) -> None:
    _log(f"== {base} ==")

    # Reset server state.
    st, txt, js = _http_json(
        "POST",
        _url(base, "/test_reset"),
        {"commands": {}, "sensors": {}},
    )
    _log(f"POST /test_reset -> {st} txt={txt.strip()!r}")

    # Hit human endpoints if OAuth is disabled (default in image).
    st, txt, js = _http_json("GET", _url(base, "/zones"))
    _log(f"GET /zones -> {st} js_keys={list(js.keys()) if isinstance(js, dict) else js}")

    # Read + post canned "twoway-like" traffic:
    # twoway: GET onboard /environment -> POST dmz /zone/<name>/sensors
    fake_envs: List[Dict[str, Any]] = [
        {"temperature_centigrade": 20.0, "humidity_percent": 40.0},
        {"temperature_centigrade": 21.5, "humidity_percent": 50.0},
        {"temperature_centigrade": 19.2, "humidity_percent": 45.0},
    ]

    for i, env in enumerate(fake_envs):
        temp = env.get("temperature_centigrade") or env.get("temp_centigrade")
        humid = env.get("humidity_percent") or env.get("humid_percent")
        payload: Dict[str, Any] = {"temp_centigrade": temp, "humid_percent": humid}

        st, txt, js = _http_json(
            "POST",
            _url(base, f"/zone/{zone}/sensors"),
            payload,
        )
        _log(f"[{i}] POST /zone/{zone}/sensors -> {st} resp_json_type={type(js).__name__}")
        # Print a small summary to avoid huge logs.
        if isinstance(js, dict):
            cmd = (js.get("command") or {})
            sns = js.get("sensors") or {}
            _log(f"    command.lolidk={cmd.get('lolidk','')!r} sensors.temp={sns.get('temp_centigrade')!r}")
        time.sleep(0.2)

    st, txt, js = _http_json("GET", _url(base, "/zones"))
    _log(f"GET /zones(after) -> {st} js_type={type(js).__name__}")

    # Access log (only works when login_required is a no-op, i.e. OAuth disabled).
    st, txt, js = _http_json("GET", _url(base, "/debug/logs"))
    _log(f"GET /debug/logs -> {st} js_type={type(js).__name__}")


def main() -> int:
    zone = os.environ.get("ZONE_NAME", "zoneymczoneface").strip()
    host = os.environ.get("DMZ_HOST", "127.0.0.1").strip()

    # Try both ports: :80 should redirect to :8080 via iptables rule in dmz-init.start.
    bases = [f"http://{host}:8080", f"http://{host}:80"]
    _log(f"dmz-smoketest: zone={zone} host={host}")

    for base in bases:
        try:
            _hit_sequence(base, zone)
        except Exception as e:
            _log(f"ERROR while hitting {base}: {e!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

