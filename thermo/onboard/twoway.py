# this probably wants its own docker container

import json
from typing import Optional, Tuple
import os
import sys
import time
from urllib.parse import urlparse, urlunparse

import requests

# Same logging as app (configured in common)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import jsonT, log, log_debug, log_error, log_warning


def info(msg: str, **kwargs) -> None:
    """Log via common.log (same format as app)."""
    log("twoway", msg, **kwargs)


def err(msg: str, **kwargs) -> None:
    """Log at ERROR (same kwargs style as info)."""
    log_error("twoway", msg, **kwargs)


def warn(msg: str, **kwargs) -> None:
    """Log at WARNING (same kwargs style as info)."""
    log_warning("twoway", msg, **kwargs)


def dbg(msg: str, **kwargs) -> None:
    """Log at DEBUG (same kwargs style as info)."""
    log_debug("twoway", msg, **kwargs)


usage = """
<name> [-d] URL1 URL2 URL3

Options:

-d deamon mode: if present, fork and return

--

A small standalone binary that:

1. GET URL1 (onboard /environment).
2. POST sensors to URL2 (DMZ /zone/<z>/sensors), signed when keys are set.
3. POST the zone JSON from DMZ to URL3 (onboard /daikin).
4. If /daikin returns 200 with a ``command`` object, POST that authoritative command
   back to DMZ ``/zone/<z>/command`` (signed) so DMZ matches merged onboard state.
5. Sleep and repeat.

URL2 must be the sensors endpoint; the command URL is derived by replacing ``/sensors`` with ``/command``.

> make dockertest
"""

info("start", argv=sys.argv)

assert len(sys.argv) == 4


readfrom = sys.argv[1]
dmz = sys.argv[2]
writeto = sys.argv[3]

# Zone name for machine auth; extracted from dmz URL path /zone/<name>/sensors
_parsed_dmz = urlparse(dmz)
_dmz_path = _parsed_dmz.path or "/"
_parts = _dmz_path.strip("/").split("/")
ZONE_NAME = os.environ.get("ZONE_NAME") or (_parts[1] if len(_parts) >= 2 else "")
ZONE_PRIVATE_KEY = os.environ.get("ZONE_PRIVATE_KEY") or os.environ.get(
    "ZONE_PRIVATE_KEY_PATH"
)


# Eagerly load the Ed25519 private key at startup so misconfiguration is loud and
# obvious BEFORE the first poll. Without this, a missing/unreadable/garbled key was
# only discovered per-request (silently per `_sign_headers`), and the only visible
# symptom was "DMZ keeps 401-ing us" with no client-side hint as to why.
SIGNING_ENABLED: bool = False
_PRIVATE_KEY_OBJ = None  # type: ignore[var-annotated]  # cryptography Ed25519PrivateKey when loaded
_KEY_FINGERPRINT: Optional[str] = None


def _probe_signing(zone_name: str, key_ref: Optional[str]) -> None:
    """Resolve and validate signing configuration; log WARN/ERROR/INFO accordingly.

    Sets module globals SIGNING_ENABLED, _PRIVATE_KEY_OBJ, _KEY_FINGERPRINT. Three outcomes:
      1) No key configured at all     -> WARN "zone auth DISABLED on client" (DMZ POSTs will 401
         if DMZ enforces auth via ZONE_PUBLIC_KEY*).
      2) Key configured but unloadable -> ERROR "zone auth MISCONFIGURED" (path missing, bad PEM,
         missing `cryptography`). Same DMZ symptom as case 1, but the cause is on us, not config.
      3) Key configured and loaded     -> INFO  "zone auth ENABLED key_sha256=… zone=…"; signing
         is on for every DMZ POST. The 16-char fingerprint matches DMZ's pub.pem fingerprint
         (see thermo/dmz/SECRETS.md), so cross-checking client vs server is one-line each side.

    A non-empty key + empty zone_name is also treated as misconfig (we cannot sign without a
    zone name in the request URL or in ZONE_NAME env).
    """
    global SIGNING_ENABLED, _PRIVATE_KEY_OBJ, _KEY_FINGERPRINT
    if not key_ref:
        warn(
            "zone auth DISABLED on client; DMZ POSTs will 401 if DMZ enforces auth. "
            "Set ZONE_PRIVATE_KEY_PATH (or ZONE_PRIVATE_KEY for inline PEM) to enable. "
            "See thermo/KEYS-AND-CERTS.md."
        )
        return
    if not zone_name:
        err(
            "zone auth MISCONFIGURED: ZONE_PRIVATE_KEY* set but ZONE_NAME is empty "
            "(could not extract from DMZ URL path /zone/<name>/sensors). Signing disabled.",
            key_ref=key_ref if not key_ref.startswith("-----") else "<inline-pem>",
        )
        return
    try:
        from zone_auth import _load_private_key, public_key_fingerprint

        key_obj = _load_private_key(key_ref)
        fingerprint = public_key_fingerprint(key_obj)
    except FileNotFoundError as e:
        err(
            "zone auth MISCONFIGURED: private key file not found. "
            "Bind-mount it into the container; see thermo/onboard/install/docker-compose.yml.",
            key_ref=key_ref,
            error=str(e),
        )
        return
    except Exception as e:
        err(
            "zone auth MISCONFIGURED: failed to load Ed25519 private key. "
            "Expected PEM (PKCS8) or 32 raw bytes. Signing disabled.",
            key_ref=key_ref if not key_ref.startswith("-----") else "<inline-pem>",
            error=f"{type(e).__name__}: {e}",
        )
        return
    SIGNING_ENABLED = True
    _PRIVATE_KEY_OBJ = key_obj
    _KEY_FINGERPRINT = fingerprint
    info(
        "zone auth ENABLED",
        zone=zone_name,
        key_sha256=fingerprint,
        key_ref=key_ref if not key_ref.startswith("-----") else "<inline-pem>",
    )


_probe_signing(ZONE_NAME, ZONE_PRIVATE_KEY)

# Request path used for Ed25519 signing (must match DMZ URL path).
DMZ_SIGN_PATH: str = _parsed_dmz.path or "/zone/default/sensors"

# POST /zone/<name>/command — same host as sensors URL; twoway pushes authoritative command.
_sensors_url_path = _parsed_dmz.path or ""
if _sensors_url_path.endswith("/sensors"):
    DMZ_COMMAND_SIGN_PATH: str = _sensors_url_path[: -len("sensors")] + "command"
else:
    DMZ_COMMAND_SIGN_PATH = _sensors_url_path.rstrip("/") + "/command"
DMZ_COMMAND_URL: str = urlunparse(
    (
        _parsed_dmz.scheme,
        _parsed_dmz.netloc,
        DMZ_COMMAND_SIGN_PATH,
        "",
        "",
        "",
    )
)

TIMEOUT_SECS: float = 10.0
PERIOD_SECS: float = 5.0
PERIOD_MAX_SECS: float = 60.0

info(
    "twoway config",
    readfrom=readfrom,
    dmz=dmz,
    writeto=writeto,
    dmz_sign_path=DMZ_SIGN_PATH,
    dmz_command_url=DMZ_COMMAND_URL,
    zone_name=ZONE_NAME or "(unset)",
    signing_enabled=SIGNING_ENABLED,
    key_sha256=_KEY_FINGERPRINT or "(none)",
    timeout_secs=TIMEOUT_SECS,
    period_max_secs=PERIOD_MAX_SECS,
    period_secs=PERIOD_SECS,
    env=os.environ.get("ENV", ""),
)


def _env_to_sensors(env: dict) -> dict:
    """Map onboard /environment response to DMZ Sensors format."""
    return {
        "temp_centigrade": env.get("temperature_centigrade")
        or env.get("temp_centigrade"),
        "humid_percent": env.get("humidity_percent") or env.get("humid_percent"),
    }


def _sign_headers(method: str, path: str, body: bytes, zonename: str) -> dict:
    """Build Ed25519 signature headers using the eagerly-loaded private key.

    Returns ``{}`` when signing is disabled (no key configured / misconfigured at startup;
    see :func:`_probe_signing`). The cached key object means we do not hit disk per request.
    """
    if not SIGNING_ENABLED or _PRIVATE_KEY_OBJ is None or not zonename:
        return {}
    try:
        import base64
        import hashlib
        import time as _time

        from zone_auth import HEADER_SIGNATURE, HEADER_TIMESTAMP, HEADER_ZONE

        ts = str(int(_time.time()))
        body_hash = hashlib.sha256(body).hexdigest()
        payload = f"{method}\n{path}\n{ts}\n{body_hash}"
        sig = _PRIVATE_KEY_OBJ.sign(payload.encode())
        return {
            HEADER_SIGNATURE: base64.b64encode(sig).decode(),
            HEADER_TIMESTAMP: ts,
            HEADER_ZONE: zonename,
        }
    except Exception as e:
        err("sign failed unexpectedly (key was loaded at startup)", error=str(e))
        return {}


def get_json(url: str, extra_headers: Optional[dict] = None) -> Tuple[jsonT, bool]:
    dbg("get request", url=url)
    headers = {"Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    r = requests.get(url, headers=headers, timeout=TIMEOUT_SECS)
    info("get response", url=url, status=r.status_code)
    if not r.ok:
        return (r.text, False)
    if not r.text:
        return ({}, True)
    try:
        return (r.json(), True)
    except Exception:
        return (f"unexpected string response: {r.text}", False)


def _push_authoritative_command_to_dmz(cmd: dict) -> bool:
    """POST merged command JSON to DMZ (bytes must match Ed25519 signature)."""
    body_bytes = json.dumps(cmd, sort_keys=True, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    extra = _sign_headers("POST", DMZ_COMMAND_SIGN_PATH, body_bytes, ZONE_NAME)
    if extra:
        headers.update(extra)
    dbg("post dmz command", url=DMZ_COMMAND_URL, body_len=len(body_bytes))
    r = requests.post(
        DMZ_COMMAND_URL, data=body_bytes, headers=headers, timeout=TIMEOUT_SECS
    )
    info("dmz command push", url=DMZ_COMMAND_URL, status=r.status_code)
    return r.status_code == 200


def post_json(
    url: str, body: dict, extra_headers: Optional[dict] = None
) -> Tuple[jsonT, bool, int]:
    """POST JSON; return (parsed-or-raw body, ok, status_code).

    status_code is 0 on transport failure (caught by caller). Callers use status_code to
    distinguish HTTP error classes — in particular 401-with-no-headers (we forgot to sign)
    from 401-with-headers (DMZ rejected the signature).
    """
    dbg("post request", url=url)
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    r = requests.post(url, json=body, headers=headers, timeout=TIMEOUT_SECS)
    info("post response", url=url, status=r.status_code)
    if r.status_code != 200:
        return (r.text, False, r.status_code)
    try:
        return (r.json(), True, r.status_code)
    except Exception:
        return (f"unexpected string response: {r.text}", False, r.status_code)


def _explain_dmz_failure(status: int, signed: bool) -> str:
    """Human-readable hint for a non-200 from the DMZ POST. Intent: stop turning a 401 into
    a head-scratcher. The two 401 cases have very different fixes."""
    if status == 401:
        if signed:
            return (
                "DMZ rejected our signed request (401). Likely causes: client key fingerprint "
                f"({_KEY_FINGERPRINT or '?'}) does not match DMZ's pub.pem; clock skew >5min; "
                "or zone name mismatch. Cross-check fingerprints (see thermo/dmz/SECRETS.md)."
            )
        return (
            "DMZ requires zone auth and we sent NO signature headers (401). Set "
            "ZONE_PRIVATE_KEY_PATH and bind-mount the priv key into the twoway container "
            "(see thermo/onboard/install/docker-compose.yml + thermo/KEYS-AND-CERTS.md)."
        )
    if status == 403:
        return f"DMZ accepted the signature but forbade the action (403). Check zone allowlist."
    if status >= 500:
        return f"DMZ server error ({status}); not our config — see DMZ logs."
    return f"DMZ returned HTTP {status}."


def poll_once() -> bool:
    try:
        env, ok_get = get_json(readfrom)
        if not ok_get:
            err("get from onboard failed: aborting poll", error=env)
            return False

        # POST to DMZ with optional machine auth
        dmz_body = _env_to_sensors(env)
        body_bytes = json.dumps(dmz_body).encode()
        extra = _sign_headers("POST", DMZ_SIGN_PATH, body_bytes, ZONE_NAME)
        signed = bool(extra)
        res, ok_dmz, status = post_json(
            dmz, dmz_body, extra_headers=extra if extra else None
        )
        dbg(f"poll_once dmz -> twoway", res=res, ok_dmz=ok_dmz, status=status)
        if not ok_dmz:
            err(
                "post to DMZ failed: aborting poll",
                status=status,
                signed=signed,
                hint=_explain_dmz_failure(status, signed),
                error=res,
            )
            return False

        # POST zone state to onboard /daikin; app.py owns conversion to State
        write_res, ok_write, _wstatus = post_json(writeto, res)
        if not ok_write:
            err("post to onboard failed: aborting poll", error=write_res, res=res)
            return False
        dbg(f"post twoway -> {writeto}", res=write_res, ok_write=ok_write)
        if isinstance(write_res, dict):
            cmd_push = write_res.get("command")
            if isinstance(cmd_push, dict) and cmd_push:
                if not _push_authoritative_command_to_dmz(cmd_push):
                    err(
                        "push authoritative command to dmz failed",
                        write_res=write_res,
                    )
                    return False
    except Exception as e:
        err("failed", error=str(e))
        return False
    return True


def poll_forever() -> None:
    info("twoway poll forever start")
    slp = PERIOD_SECS
    while True:
        info(f"sleep: {slp}")
        time.sleep(slp)
        ok = poll_once()
        if ok:
            slp = PERIOD_SECS
        else:
            slp = min(PERIOD_MAX_SECS, slp + 1)


info("enter")
if __name__ == "__main__":
    if os.environ.get("ENV") in ["DOCKERTEST"]:
        PERIOD_SECS = 0.1
        info("twoway dockertest override", period_secs=PERIOD_SECS)
    poll_forever()
info("exit")
