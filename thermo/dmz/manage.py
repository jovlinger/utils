#!/usr/bin/env venv-run
"""
CLI for the DMZ HTTP API (see app.py).

Uses DMZ_URL as the service base URL. Authenticates like onboard/twoway when
ZONE_PRIVATE_KEY or ZONE_PRIVATE_KEY_PATH is set: Ed25519 request signing via
zone_auth (same headers as POST /zone/<name>/sensors).

For GET /zones and GET /debug/logs, signing sends X-Zone-Name (defaults to
``cli`` when ZONE_NAME is unset; the DMZ verifies one shared public key — the
name is not used to pick a key). Zone-scoped commands use the zone from the
CLI argument.

Usage:
  DMZ_URL=http://host:5000   # or host:5000 (treated as http://…)
  ZONE_PRIVATE_KEY_PATH=... \\
    manage <action> [args...]

Optional: ZONE_NAME — only needed when it differs from the zone you pass on
the command line (``command``/``sensors``/``updatezone``). Omit for ``zones``,
``debug_logs``, and ``healthz``.

Actions (first arg) map to app routes:
  help                          — full documentation (this module docstring)
  login | authorize | logout     — GET OAuth helpers (browser-oriented)
  sensors <zone> [body...]       — POST /zone/<zone>/sensors
  command <zone> [body...]      — POST /zone/<zone>/command
  zones                         — GET /zones
  healthz                       — GET /ui/diagnostics (unsigned; uptime, config, access tail)
  debug_logs | logs             — GET /debug/logs
  test_reset [json]             — POST /test_reset (unsigned; testing only)
  updatezone <zone> key=val...  — GET /zones, merge key=val into command, POST command
    (see common.heatpumpirctl.State; run updatezone with no args for a full JSON example)

Body arguments for sensors/command: either one JSON object string, or key=value pairs
(e.g. mode=HEAT temp_c=22 power=true).

manage zones
One zone: dump current zone JSON (from GET /zones, then print that entry)

manage updatezone myzone
One zone: merge key=value into that zone’s command and POST

manage updatezone myzone power=true mode=HEAT half_c=45 fan=F4

Direct POSTs (body is either key=value pairs or one JSON object string)

manage sensors myzone temp_centigrade=20.5
manage command myzone '{"power": true, "mode": "HEAT", "temp_c": 22}'
OAuth helpers (browser-oriented; no zone signing)

manage login
manage authorize
manage logout
Debug logs

manage healthz
  DMZ_URL=http://your-host:5000 manage healthz
manage debug_logs
# same as:
manage logs
Test reset (unsigned; testing)

manage test_reset
Machine auth: one Ed25519 keypair for the whole DMZ (``ZONE_PRIVATE_KEY`` or
``ZONE_PRIVATE_KEY_PATH``). Zone-scoped actions take the zone name as a CLI arg.

"""

from __future__ import annotations

import json
import os
import sys
import warnings
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse

# macOS system/LibreSSL Pythons trigger urllib3 v2 noise on import; harmless for this CLI.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# Repo layout: thermo/dmz/manage.py -> thermo/onboard/common/heatpumpirctl (State)
_ONBOARD_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "onboard"))

# When common.heatpumpirctl is not importable, help text still matches
# State.to_json() for the same builder chain. Keep in sync with onboard.
_FALLBACK_ONBOARD_STATE_EXAMPLE: Dict[str, Any] = {
    "power": True,
    "mode": "HEAT",
    "half_c": 45,
    "fan": "F4",
    "swing": True,
    "powerful": True,
    "econo": False,
    "comfort": True,
    "timer_on_active": True,
    "timer_off_active": True,
    "timer_on_minutes": 90,
    "timer_off_minutes": 120,
}


def _die(msg: str, code: int = 2) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _print_help() -> int:
    print((__doc__ or "").strip())
    return 0


def _usage() -> int:
    print(
        "usage: manage "
        "{help|login|authorize|logout|sensors|command|zones|healthz|debug_logs|logs|test_reset|updatezone} ...",
        file=sys.stderr,
    )
    print(
        "Set DMZ_URL to the DMZ base. Example:\n"
        "  DMZ_URL=http://your-host:5000 manage healthz\n"
        "Run manage help for full documentation.",
        file=sys.stderr,
    )
    return 0


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


def _sign_zone_name(explicit: str = "") -> str:
    """Zone label for X-Zone-Name when signing (one DMZ pub key; name is not a key selector)."""
    return explicit.strip() or _zone_name_default() or "cli"


def _project_venv_python() -> Optional[str]:
    """Preferred project venv interpreter (.venv, venv, then legacy env/)."""
    for sub in (".venv", "venv", "env"):
        py = os.path.join(SCRIPT_DIR, sub, "bin", "python")
        if os.path.isfile(py):
            return py
    return None


def _venv_chained_to_bin_venv(venv_python: str) -> bool:
    """True when project .venv/bin/python resolves into jovlinger/bin/.venv."""
    try:
        resolved = os.path.realpath(venv_python)
    except OSError:
        return False
    return f"{os.sep}bin{os.sep}.venv{os.sep}" in resolved


def _warn_if_wrong_interpreter() -> None:
    """Warn when manage.py runs under bin/.venv or a .venv chained to it."""
    expected = _project_venv_python()
    if not expected:
        return
    exe = os.path.realpath(sys.executable)
    want = os.path.realpath(expected)
    utils_root = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
    create_pipenv = os.path.join(utils_root, "create_pipenv.sh")
    activate = os.path.join(SCRIPT_DIR, ".venv", "bin", "activate")

    if _venv_chained_to_bin_venv(expected):
        print(
            "warning: thermo/dmz/.venv is chained to bin/.venv "
            f"({want}).\n"
            "  It was likely created while bin/.venv was active.\n"
            f"  deactivate\n"
            f"  rm -rf {os.path.join(SCRIPT_DIR, '.venv')}\n"
            f"  {create_pipenv} thermo/dmz\n"
            f"  source {activate}",
            file=sys.stderr,
        )
        return

    if exe == want:
        return
    bin_marker = f"{os.sep}bin{os.sep}.venv{os.sep}"
    if bin_marker in exe:
        wrong = "bin/.venv is active — wrong tree for thermo/dmz"
    else:
        wrong = f"not {want}"
    print(
        f"warning: manage.py interpreter ({sys.executable}) is {wrong}.\n"
        f"  deactivate   # if bin/.venv is active\n"
        f"  source {activate}\n"
        f"  # or create: {create_pipenv} thermo/dmz",
        file=sys.stderr,
    )


def _cryptography_install_hint() -> str:
    """How to install cryptography into thermo/dmz/.venv (not bin/.venv or system)."""
    py = sys.executable
    req = os.path.join(SCRIPT_DIR, "requirements.txt")
    project_py = _project_venv_python()
    venv_activate = (
        os.path.join(os.path.dirname(project_py), "activate")
        if project_py
        else os.path.join(SCRIPT_DIR, ".venv", "bin", "activate")
    )
    utils_root = os.path.normpath(os.path.join(SCRIPT_DIR, "..", ".."))
    create_pipenv = os.path.join(utils_root, "create_pipenv.sh")
    lines = [
        "signing requires cryptography in thermo/dmz's project venv (.venv),",
        "not bin/.venv and not a system-wide pip install.",
        f"Current interpreter: {py}",
        "",
    ]
    if project_py and _venv_chained_to_bin_venv(project_py):
        lines.extend(
            [
                "thermo/dmz/.venv is chained to bin/.venv — recreate it:",
                f"  deactivate",
                f"  rm -rf {os.path.join(SCRIPT_DIR, '.venv')}",
                f"  {create_pipenv} thermo/dmz",
                f"  source {venv_activate}",
                f"  manage ...",
            ]
        )
        return "\n".join(lines)
    if project_py and os.path.realpath(py) != os.path.realpath(project_py):
        lines.extend(
            [
                "Use the project venv (recommended):",
                f"  deactivate                    # drop bin/.venv if active",
                f"  {create_pipenv} thermo/dmz",
                f"  source {venv_activate}",
                f"  manage ...",
                "",
            ]
        )
    if os.path.isfile(venv_activate):
        lines.extend(
            [
                "Or install into the project venv explicitly:",
                f"  {project_py or os.path.join(SCRIPT_DIR, '.venv', 'bin', 'python')} -m pip install -r {req}",
            ]
        )
    else:
        lines.extend(
            [
                "Create the project venv first:",
                f"  {create_pipenv} thermo/dmz",
                f"  source {venv_activate}",
                f"  manage ...",
            ]
        )
    return "\n".join(lines)


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
    except RuntimeError as exc:
        if "cryptography not installed" in str(exc):
            _die(_cryptography_install_hint(), code=1)
        _die(f"signing failed: {exc}", code=1)
    except ValueError as exc:
        _die(f"signing failed: {exc}", code=1)
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


def _connection_error_message(url: str, exc: BaseException) -> str:
    """One-line hint when DMZ_URL does not resolve or accept a connection."""
    parsed = urlparse(url)
    host = parsed.netloc or parsed.hostname or url
    msg = str(exc.__cause__ or exc).strip() or type(exc).__name__
    lower = msg.lower()
    if any(
        needle in lower
        for needle in (
            "nodename nor servname",
            "name or service not known",
            "getaddrinfo failed",
            "temporary failure in name resolution",
            "failed to resolve",
        )
    ):
        return f"DMZ unreachable: host not found ({host!r}; check DMZ_URL)"
    if "connection refused" in lower:
        return f"DMZ unreachable: connection refused ({url})"
    if "network is unreachable" in lower:
        return f"DMZ unreachable: network unreachable ({host})"
    if "timed out" in lower or "timeout" in lower:
        return f"DMZ unreachable: timed out ({url})"
    first_line = msg.splitlines()[0]
    return f"DMZ unreachable: {first_line} ({url})"


def _is_oauth_redirect(location: str) -> bool:
    """True when Location is DMZ /login or an external OAuth/Sign-In URL."""
    if not location:
        return False
    parsed = urlparse(location if "://" in location else f"http://x{location}")
    path = (parsed.path or location).lower()
    if path.rstrip("/") in ("/login", "/authorize", "/logout"):
        return True
    host = (parsed.netloc or "").lower()
    if "accounts.google.com" in host or host.endswith(".google.com"):
        return True
    return "oauth" in path or "signin" in path


def _redirect_error_message(url: str, response: requests.Response) -> str:
    loc = (response.headers.get("Location") or "").strip()
    if loc and not loc.startswith(("http://", "https://")):
        base = urlparse(url)
        loc = urljoin(f"{base.scheme}://{base.netloc}/", loc.lstrip("/"))
    target = f" → {loc}" if loc else ""
    if _is_oauth_redirect(loc):
        return (
            f"DMZ OAuth redirect: {response.status_code}{target} "
            f"(authentication required; set ZONE_PRIVATE_KEY or ZONE_PRIVATE_KEY_PATH for machine auth)"
        )
    return f"DMZ unexpected redirect: {response.status_code}{target} ({url})"


def _html_instead_of_json_message(url: str, body: str = "") -> str:
    lower = body[:4096].lower()
    if (
        "accounts.google.com" in lower
        or "signin" in lower
        or _is_oauth_redirect(url)
    ):
        return (
            f"DMZ OAuth redirect: received HTML login page instead of JSON ({url}). "
            "Set ZONE_PRIVATE_KEY or ZONE_PRIVATE_KEY_PATH for machine auth."
        )
    return (
        f"DMZ returned HTML instead of JSON ({url}). "
        "Expected JSON; check DMZ_URL and authentication."
    )


def _http_request(
    method: str,
    url: str,
    *,
    headers: Dict[str, str],
    data: Optional[bytes],
    timeout: int,
) -> requests.Response:
    try:
        if method.upper() == "GET":
            return requests.get(
                url, headers=headers, timeout=timeout, allow_redirects=False
            )
        if method.upper() == "POST":
            return requests.post(
                url, data=data, headers=headers, timeout=timeout, allow_redirects=False
            )
        _die(f"unsupported method: {method}")
    except requests.exceptions.Timeout:
        _die(f"DMZ unreachable: timed out after {timeout}s ({url})", code=1)
    except requests.exceptions.SSLError as exc:
        _die(f"DMZ TLS error: {exc} ({url})", code=1)
    except requests.exceptions.ConnectionError as exc:
        _die(_connection_error_message(url, exc), code=1)
    except requests.exceptions.RequestException as exc:
        _die(f"DMZ request failed: {exc} ({url})", code=1)
    raise AssertionError("unreachable")


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
    r = _http_request(method, url, headers=headers, data=data, timeout=60)
    if 300 <= r.status_code < 400:
        _die(_redirect_error_message(url, r), code=1)
    if not r.content:
        return r.status_code, None
    ctype = (r.headers.get("Content-Type") or "").lower()
    if "application/json" in ctype:
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, r.text
    text = r.text
    if "text/html" in ctype or text.lstrip().startswith("<"):
        _die(_html_instead_of_json_message(url, text), code=1)
    return r.status_code, text


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
    """Fully-populated common.heatpumpirctl.State as .to_json() (same shape as /daikin command)."""
    if _ONBOARD_ROOT not in sys.path:
        sys.path.insert(0, _ONBOARD_ROOT)
    try:
        from common.heatpumpirctl import Fan, Mode, State
    except ImportError:
        return dict(_FALLBACK_ONBOARD_STATE_EXAMPLE)

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
        "usage: manage updatezone <zone> key=value ...\n"
        "\n"
        "Merges each key=value into the zone's command dict and POSTs it. Key names match "
        "common.heatpumpirctl.State.to_json() / from_json() - the same object you send as "
        '{"command": ...} to POST /daikin on the Pi. The DMZ stores the command object '
        "as JSON (7-bit ASCII strings only); onboard owns parsing and IR.\n"
        "\n"
        "Fully-populated onboard State example (.to_json()):\n"
        f"{pretty}\n"
        "\n"
        "Same payload as one line of flat key=value args:\n"
        f"  manage updatezone <zone> {pretty_kv}\n"
        "\n"
        "Note: from_json() also accepts temp_c (°C) instead of half_c. "
        "mode: AUTO, DRY, COOL, HEAT, FAN. fan: F1..F5, AUTO, SILENT."
    )


def _cmd_updatezone(zone: str, kv_args: List[str]) -> int:
    key_mat = _zone_private_key_material()
    zn = _sign_zone_name(zone)

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
    _warn_if_wrong_interpreter()
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _usage()
    action = args[0]
    rest = args[1:]

    if action == "help":
        return _print_help()

    # OAuth helpers: no machine signing (browser flow).
    if action in ("login", "authorize", "logout"):
        path = f"/{action}"
        st, body = _request_json("GET", path, zone_for_sign="", sign=False)
        return _emit(st, body)

    if action == "zones":
        key_mat = _zone_private_key_material()
        st, body = _request_json(
            "GET",
            "/zones",
            zone_for_sign=_sign_zone_name(),
            sign=bool(key_mat),
        )
        return _emit(st, body)

    if action == "healthz":
        st, body = _request_json(
            "GET",
            "/ui/diagnostics",
            zone_for_sign="",
            sign=False,
        )
        return _emit(st, body)

    if action in ("debug_logs", "logs"):
        key_mat = _zone_private_key_material()
        st, body = _request_json(
            "GET",
            "/debug/logs",
            zone_for_sign=_sign_zone_name(),
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
