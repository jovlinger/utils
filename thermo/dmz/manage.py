#!/usr/bin/env python3
"""
CLI for the DMZ HTTP API (see app.py).

Uses DMZ_URL as the service base URL. Authenticates like onboard/twoway when
ZONE_PRIVATE_KEY or ZONE_PRIVATE_KEY_PATH is set: Ed25519 request signing via
zone_auth (same headers as POST /zone/<name>/sensors).

For GET /zones and GET /debug/logs, signing uses ZONE_NAME in X-Zone-Name
(see onboard run.sh / twoway).

Usage:
  DMZ_URL=http://host:5000   # or host:5000 (treated as http://…)
  ZONE_NAME=myzone ZONE_PRIVATE_KEY_PATH=... \\
    python manage.py <action> [args...]

Actions (first arg) map to app routes:
  login | authorize | logout     — GET OAuth helpers (browser-oriented)
  sensors <zone> [body...]       — POST /zone/<zone>/sensors
  command <zone> [body...]      — POST /zone/<zone>/command
  zones                         — GET /zones
  debug_logs | logs             — GET /debug/logs
  test_reset [json]             — POST /test_reset (unsigned; testing only)
  updatezone <zone> key=val...  — GET /zones, merge key=val into command, POST command
    (see onboard heatpumpirctl.State; run updatezone with no args for a full JSON example)

Body arguments for sensors/command: either one JSON object string, or key=value pairs
(e.g. lolidk=heat_22 temp_centigrade=21.5).

python manage.py zones
One zone: dump current zone JSON (from GET /zones, then print that entry)

python manage.py updatezone myzone
One zone: merge key=value into that zone’s command and POST

python manage.py updatezone myzone power=true mode=HEAT half_c=45 fan=F4

Direct POSTs (body is either key=value pairs or one JSON object string)

python manage.py sensors myzone temp_centigrade=20.5
python manage.py command myzone '{"lolidk": "heat_22"}'
OAuth helpers (browser-oriented; no zone signing)

python manage.py login
python manage.py authorize
python manage.py logout
Debug logs

python manage.py debug_logs
# same as:
python manage.py logs
Test reset (unsigned; testing)

python manage.py test_reset
For zones / debug_logs with a private key configured, manage.py requires ZONE_NAME for signing the GET; for updatezone, it uses ZONE_NAME if set, otherwise the zone name you pass.

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

# Repo layout: thermo/dmz/manage.py → thermo/onboard/heatpumpirctl (State)
_ONBOARD_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "onboard"))


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _dmz_base() -> str:
    """
    Resolve DMZ_URL using urllib.parse.

    Full URLs (http:// or https://) are validated as-is. A scheme-less base
    (e.g. 192.168.88.200:5000 or dmz.local) is treated as http://… so requests
    gets a proper scheme.
    """
    raw = os.environ.get("DMZ_URL", "").strip()
    if not raw:
        _die("DMZ_URL is not set")

    parsed = urlparse(raw)
    if parsed.scheme in ("http", "https"):
        if not parsed.netloc:
            _die(
                "DMZ_URL must include a host, e.g. http://dmz.local:5000\n"
                f"  (got {raw!r})"
            )
        return raw.rstrip("/")

    if parsed.scheme:
        _die(f"DMZ_URL must use http or https (got scheme {parsed.scheme!r})")

    # No scheme: urlparse puts "host:port" in .path, not .netloc — try http:// + raw
    candidate = "http://" + raw.lstrip("/")
    trial = urlparse(candidate)
    if trial.scheme == "http" and trial.netloc:
        return candidate.rstrip("/")

    _die(
        "DMZ_URL is not a valid base URL. Use http:// or https:// with a host "
        "(e.g. http://192.168.88.200:5000), or host:port alone for plain HTTP.\n"
        f"  (got {raw!r})"
    )


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


def _onboard_state_example_dict() -> Dict[str, Any]:
    """Fully-populated onboard heatpumpirctl.State as .to_json() (same shape as /daikin command)."""
    if _ONBOARD_ROOT not in sys.path:
        sys.path.insert(0, _ONBOARD_ROOT)
    from heatpumpirctl import Fan, Mode, State

    s = (
        State()
        .set_power(True)
        .set_mode(Mode.HEAT)
        .set_temp(22.5)
        .set_fan(Fan.F4)
        .set_swing(True)
        .set_powerful(True)
        .set_econo(False)
        .set_comfort(True)
        .set_timer_on(90)
        .set_timer_off(120)
    )
    return s.to_json()


def _flat_dict_as_updatezone_kv_args(d: Dict[str, Any]) -> str:
    """Format a flat dict as `updatezone` key=value tokens (sorted keys, ASCII-safe)."""
    tokens: List[str] = []
    for key in sorted(d.keys()):
        val = d[key]
        if isinstance(val, bool):
            tokens.append(f"{key}={'true' if val else 'false'}")
        elif isinstance(val, str):
            tokens.append(f"{key}={val}")
        elif isinstance(val, (int, float)):
            tokens.append(f"{key}={val}")
        elif val is None:
            tokens.append(f"{key}=")
        else:
            tokens.append(f"{key}={json.dumps(val, separators=(',', ':'))}")
    return " ".join(tokens)


def _updatezone_help_message() -> str:
    example = _onboard_state_example_dict()
    pretty = json.dumps(example, indent=2, sort_keys=True)
    pretty_kv = _flat_dict_as_updatezone_kv_args(example)
    return (
        "usage: manage.py updatezone <zone> key=value ...\n"
        "\n"
        "Merges each key=value into the zone's command dict and POSTs it. Key names match "
        "onboard heatpumpirctl.State.to_json() / from_json() — the same object you send as "
        '{"command": ...} to POST /daikin on the Pi. The DMZ stores the command object '
        "as JSON (7-bit ASCII strings only); onboard owns parsing and IR.\n"
        "\n"
        "Fully-populated onboard State example (.to_json()):\n"
        f"{pretty}\n"
        "\n"
        "Same payload as one line of flat key=value args:\n"
        f"  manage.py updatezone <zone> {pretty_kv}\n"
        "\n"
        "Note: from_json() also accepts temp_c (°C) instead of half_c. "
        "mode: AUTO, DRY, COOL, HEAT, FAN. fan: F1..F5, AUTO, SILENT."
    )


def _cmd_updatezone(zone: str, kv_args: List[str]) -> int:
    key_mat = _zone_private_key_material()
    zn = _zone_name_default() or zone

    def _fetch_zone_entry() -> (
        Tuple[int, Union[dict, list, str, None], Optional[Dict[str, Any]]]
    ):
        st, all_zones = _request_json(
            "GET",
            "/zones",
            zone_for_sign=zn,
            body=None,
            sign=bool(key_mat),
        )
        if st != 200:
            return st, all_zones, None
        if not isinstance(all_zones, dict):
            _die("unexpected /zones response shape")
        raw = all_zones.get(zone)
        if raw is not None and not isinstance(raw, dict):
            _die(f"unexpected zone payload for {zone!r}")
        return st, all_zones, raw

    if not kv_args:
        print(_updatezone_help_message(), file=sys.stderr)
        st, body, zstate = _fetch_zone_entry()
        if st != 200:
            return _emit(st, body)
        if zstate is None:
            print(f"zone not found: {zone!r}", file=sys.stderr)
            return 1
        print(json.dumps(zstate, indent=2, sort_keys=True))
        return 0

    st, all_zones, zstate = _fetch_zone_entry()
    if st != 200:
        return _emit(st, all_zones)
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
            _die(_updatezone_help_message())
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
