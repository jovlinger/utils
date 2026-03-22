#!/usr/bin/env python3
"""
CLI for the DMZ HTTP API (see app.py).

Uses DMZ_URL as the service base URL. Authenticates like onboard/twoway when
ZONE_PRIVATE_KEY or ZONE_PRIVATE_KEY_PATH is set: Ed25519 request signing via
zone_auth (same headers as POST /zone/<name>/sensors).

For GET /zones and GET /debug/logs, signing uses ZONE_NAME in X-Zone-Name
(see onboard run.sh / twoway).

Usage:
  DMZ_URL=http://host:5000 ZONE_NAME=myzone ZONE_PRIVATE_KEY_PATH=... \\
    python manage.py <action> [args...]

Actions (first arg) map to app routes:
  login | authorize | logout     — GET OAuth helpers (browser-oriented)
  sensors <zone> [body...]       — POST /zone/<zone>/sensors
  command <zone> [body...]      — POST /zone/<zone>/command
  zones                         — GET /zones
  debug_logs | logs             — GET /debug/logs
  test_reset [json]             — POST /test_reset (unsigned; testing only)
  updatezone <zone> key=val...  — GET /zones, merge key=val into command, POST command

Body arguments for sensors/command: either one JSON object string, or key=value pairs
(e.g. lolidk=heat_22 temp_centigrade=21.5).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _dmz_base() -> str:
    raw = os.environ.get("DMZ_URL", "").strip()
    if not raw:
        _die("DMZ_URL is not set")
    return raw.rstrip("/")


def _zone_private_key_material() -> str:
    return (
        os.environ.get("ZONE_PRIVATE_KEY", "").strip()
        or os.environ.get("ZONE_PRIVATE_KEY_PATH", "").strip()
    )


def _zone_name_default() -> str:
    return os.environ.get("ZONE_NAME", "").strip()


def _sign_headers(method: str, path: str, body: bytes, zonename: str) -> Dict[str, str]:
    """Add Ed25519 signature headers if a private key is configured (onboard-style)."""
    key = _zone_private_key_material()
    if not key or not zonename:
        return {}
    try:
        from zone_auth import (
            HEADER_SIGNATURE,
            HEADER_TIMESTAMP,
            HEADER_ZONE,
            sign_request,
        )

        sig, ts, _zn = sign_request(method, path, body, zonename, key)
        return {
            HEADER_SIGNATURE: sig,
            HEADER_TIMESTAMP: ts,
            HEADER_ZONE: zonename,
        }
    except Exception as exc:  # pragma: no cover - CLI surface
        _die(f"signing failed: {exc}", code=1)


def _parse_body_args(argv: List[str]) -> Dict[str, Any]:
    """Build JSON body from CLI args: one JSON object, or key=value pairs."""
    if not argv:
        return {}
    if len(argv) == 1 and argv[0].lstrip().startswith("{"):
        try:
            parsed = json.loads(argv[0])
        except json.JSONDecodeError as exc:
            _die(f"invalid JSON body: {exc}")
        if not isinstance(parsed, dict):
            _die("JSON body must be an object")
        return parsed
    out: Dict[str, Any] = {}
    for item in argv:
        if "=" not in item:
            _die(f"expected key=value or one JSON object, got: {item!r}")
        key, _, val = item.partition("=")
        key = key.strip()
        if not key:
            _die(f"empty key in: {item!r}")
        out[key] = val.strip()
    return out


def _json_dumps_body(payload: Dict[str, Any]) -> bytes:
    # Must match the bytes sent on the wire (see twoway / zone_auth).
    return json.dumps(payload).encode("utf-8")


def _request_json(
    method: str,
    path: str,
    *,
    zone_for_sign: str,
    body: Optional[Dict[str, Any]] = None,
    sign: bool = True,
) -> Tuple[int, Union[dict, list, str, None]]:
    base = _dmz_base()
    url = urljoin(base + "/", path.lstrip("/"))
    headers: Dict[str, str] = {"Accept": "application/json"}
    data: Optional[bytes] = None
    if body is not None:
        data = _json_dumps_body(body)
        headers["Content-Type"] = "application/json"
    body_bytes = data if data is not None else b""
    if sign:
        parsed = urlparse(url)
        req_path = parsed.path or "/"
        if parsed.query:
            req_path = f"{req_path}?{parsed.query}"
        headers.update(_sign_headers(method, req_path, body_bytes, zone_for_sign))
    if method.upper() == "GET":
        r = requests.get(url, headers=headers, timeout=60)
    elif method.upper() == "POST":
        r = requests.post(url, data=data, headers=headers, timeout=60)
    else:
        _die(f"unsupported method: {method}")
    if not r.content:
        return r.status_code, None
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text
    return r.status_code, r.text


def _emit(status: int, body: Union[dict, list, str, None]) -> int:
    if status >= 400:
        print(body if isinstance(body, str) else json.dumps(body), file=sys.stderr)
        return 1
    if body is None:
        return 0
    if isinstance(body, (dict, list)):
        print(json.dumps(body, indent=2, sort_keys=True))
    else:
        print(body)
    return 0


def _cmd_updatezone(zone: str, kv_args: List[str]) -> int:
    if not kv_args:
        _die("updatezone requires at least one key=value")
    key_mat = _zone_private_key_material()
    zn = _zone_name_default() or zone
    st, all_zones = _request_json(
        "GET",
        "/zones",
        zone_for_sign=zn,
        body=None,
        sign=bool(key_mat),
    )
    if st != 200:
        return _emit(st, all_zones)
    if not isinstance(all_zones, dict):
        _die("unexpected /zones response shape")
    zstate = all_zones.get(zone)
    if zstate is None:
        _die(f"zone not found: {zone!r}")
    cmd_obj = zstate.get("command")
    cmd: Dict[str, Any] = dict(cmd_obj) if isinstance(cmd_obj, dict) else {}
    for item in kv_args:
        if "=" not in item:
            _die(f"expected key=value, got: {item!r}")
        k, _, v = item.partition("=")
        k = k.strip()
        if not k:
            _die(f"empty key in: {item!r}")
        cmd[k] = v.strip()
    st2, resp = _request_json(
        "POST",
        f"/zone/{zone}/command",
        zone_for_sign=zone,
        body=cmd,
        sign=True,
    )
    return _emit(st2, resp)


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        _die(
            "usage: manage.py "
            "{login|authorize|logout|sensors|command|zones|debug_logs|logs|test_reset|updatezone} ..."
        )
    action = args[0]
    rest = args[1:]

    # OAuth helpers: no machine signing (browser flow).
    if action in ("login", "authorize", "logout"):
        path = f"/{action}"
        st, body = _request_json("GET", path, zone_for_sign="", sign=False)
        return _emit(st, body)

    if action == "zones":
        key_mat = _zone_private_key_material()
        zn = _zone_name_default()
        if key_mat and not zn:
            _die("zones: set ZONE_NAME when using ZONE_PRIVATE_KEY for signing")
        st, body = _request_json(
            "GET",
            "/zones",
            zone_for_sign=zn,
            sign=bool(key_mat),
        )
        return _emit(st, body)

    if action in ("debug_logs", "logs"):
        key_mat = _zone_private_key_material()
        zn = _zone_name_default()
        if key_mat and not zn:
            _die("debug_logs: set ZONE_NAME when using ZONE_PRIVATE_KEY for signing")
        st, body = _request_json(
            "GET",
            "/debug/logs",
            zone_for_sign=zn,
            sign=bool(key_mat),
        )
        return _emit(st, body)

    if action == "test_reset":
        payload = _parse_body_args(rest) if rest else {"commands": {}, "sensors": {}}
        st, body = _request_json(
            "POST",
            "/test_reset",
            zone_for_sign="",
            body=payload,
            sign=False,
        )
        return _emit(st, body)

    if action == "updatezone":
        if not rest:
            _die("updatezone <zone> key=value ...")
        zone = rest[0]
        return _cmd_updatezone(zone, rest[1:])

    if action == "sensors":
        if not rest:
            _die("sensors <zone> [key=value | JSON object]")
        zone = rest[0]
        payload = _parse_body_args(rest[1:])
        st, body = _request_json(
            "POST",
            f"/zone/{zone}/sensors",
            zone_for_sign=zone,
            body=payload,
            sign=True,
        )
        return _emit(st, body)

    if action == "command":
        if not rest:
            _die("command <zone> [key=value | JSON object]")
        zone = rest[0]
        payload = _parse_body_args(rest[1:])
        st, body = _request_json(
            "POST",
            f"/zone/{zone}/command",
            zone_for_sign=zone,
            body=payload,
            sign=True,
        )
        return _emit(st, body)

    _die(f"unknown action: {action!r}")


if __name__ == "__main__":
    raise SystemExit(main())
