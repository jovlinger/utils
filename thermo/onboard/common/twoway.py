# this probably wants its own docker container

import json
import logging
import os
import socket
import sys
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import jsonT
from common.deploy_metadata import deployment_post_metadata
from common.logging_config import configure_logging, format_kv, get_recent_log_messages

configure_logging("twoway")
# Example: 2026-05-17T13:40:23.905Z INFO twoway twoway:45 start argv=['common.twoway', 'http://...', ...]
logger = logging.getLogger(__name__)


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

logger.info("start%s", format_kv(argv=sys.argv))

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
        logger.warning(
            "zone auth DISABLED on client; DMZ POSTs will 401 if DMZ enforces auth. "
            "Set ZONE_PRIVATE_KEY_PATH (or ZONE_PRIVATE_KEY for inline PEM) to enable. "
            "See thermo/KEYS-AND-CERTS.md."
        )
        return
    if not zone_name:
        logger.error(
            "zone auth MISCONFIGURED: ZONE_PRIVATE_KEY* set but ZONE_NAME is empty "
            "(could not extract from DMZ URL path /zone/<name>/sensors). Signing disabled.%s",
            format_kv(
                key_ref=key_ref if not key_ref.startswith("-----") else "<inline-pem>",
            ),
        )
        return
    try:
        from common.zone_auth import _load_private_key, public_key_fingerprint

        key_obj = _load_private_key(key_ref)
        fingerprint = public_key_fingerprint(key_obj)
    except FileNotFoundError as e:
        logger.error(
            "zone auth MISCONFIGURED: private key file not found. "
            "Bind-mount it into the container or set ZONE_PRIVATE_KEY_PATH.%s",
            format_kv(key_ref=key_ref, error=str(e)),
        )
        return
    except Exception as e:
        logger.error(
            "zone auth MISCONFIGURED: failed to load Ed25519 private key. "
            "Expected PEM (PKCS8) or 32 raw bytes. Signing disabled.%s",
            format_kv(
                key_ref=key_ref if not key_ref.startswith("-----") else "<inline-pem>",
                error=f"{type(e).__name__}: {e}",
            ),
        )
        return
    SIGNING_ENABLED = True
    _PRIVATE_KEY_OBJ = key_obj
    _KEY_FINGERPRINT = fingerprint
    logger.info(
        "zone auth ENABLED%s",
        format_kv(
            zone=zone_name,
            key_sha256=fingerprint,
            key_ref=key_ref if not key_ref.startswith("-----") else "<inline-pem>",
        ),
    )


_probe_signing(ZONE_NAME, ZONE_PRIVATE_KEY)

# Request path used for Ed25519 signing (must match DMZ URL path).
DMZ_SIGN_PATH: str = _parsed_dmz.path or "/zone/default/sensors"


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


# Onboard GET/POST are fast; DMZ POST /zone/.../sensors long-polls (see DMZ LONG_POLL_*).
ONBOARD_HTTP_TIMEOUT_SECS: float = _env_float("ONBOARD_HTTP_TIMEOUT_SECS", 10.0)
_LONG_POLL_TIMEOUT_SECS: float = _env_float("LONG_POLL_TIMEOUT_SECS", 60.0)
_DMZ_HTTP_TIMEOUT_MARGIN_SECS: float = _env_float("DMZ_HTTP_TIMEOUT_MARGIN_SECS", 10.0)
DMZ_HTTP_TIMEOUT_SECS: float = _env_float(
    "DMZ_HTTP_TIMEOUT_SECS",
    _LONG_POLL_TIMEOUT_SECS + _DMZ_HTTP_TIMEOUT_MARGIN_SECS,
)

PERIOD_SECS: float = 5.0
PERIOD_MAX_SECS: float = 60.0
logger.info(
    "twoway config%s",
    format_kv(
        readfrom=readfrom,
        dmz=dmz,
        writeto=writeto,
        dmz_sign_path=DMZ_SIGN_PATH,
        zone_name=ZONE_NAME or "(unset)",
        signing_enabled=SIGNING_ENABLED,
        key_sha256=_KEY_FINGERPRINT or "(none)",
        onboard_http_timeout_secs=ONBOARD_HTTP_TIMEOUT_SECS,
        dmz_http_timeout_secs=DMZ_HTTP_TIMEOUT_SECS,
        long_poll_timeout_secs=_LONG_POLL_TIMEOUT_SECS,
        period_max_secs=PERIOD_MAX_SECS,
        period_secs=PERIOD_SECS,
        env=os.environ.get("ENV", ""),
    ),
)


def _env_to_dmz_body(env: dict) -> dict:
    """Build nested DMZ POST body from onboard /environment response.

    Shape: ``{"sensors": {...}, "command": {...}}`` -- DMZ accepts the optional
    ``command`` field as a piggybacked onboard-side command and applies its strictly-newer
    ``created_dt`` gate. ``command`` is omitted when onboard has never applied one
    (cold start), so DMZ never sees a misleading empty command.
    """
    body: dict = {
        "sensors": {
            "temp_centigrade": env.get("temperature_centigrade")
            or env.get("temp_centigrade"),
            "humid_percent": env.get("humidity_percent") or env.get("humid_percent"),
        }
    }
    cmd = env.get("command") if isinstance(env, dict) else None
    if isinstance(cmd, dict) and cmd:
        body["command"] = cmd
    logs = _combined_log_lines(env)
    if logs:
        body["logs"] = {"lines": logs}
    network = env.get("network") if isinstance(env, dict) else None
    if isinstance(network, dict) and network:
        body["network"] = network
    else:
        network = _network_metadata_from_os()
        if network:
            body["network"] = network
    body["deployment"] = deployment_post_metadata()
    return body


def _best_effort_local_ip() -> Optional[str]:
    """Return the outbound local IPv4 address, if the OS can infer one."""
    override = os.environ.get("ONBOARD_LOCAL_IP", "").strip()
    if override:
        return override
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 80))
            return str(sock.getsockname()[0])
    except OSError:
        return None


def _network_metadata_from_os() -> Dict[str, str]:
    """Best-effort local network metadata for DMZ zone state."""
    metadata: Dict[str, str] = {}
    local_ip = _best_effort_local_ip()
    if local_ip:
        metadata["local_ip"] = local_ip
        metadata["onboard_url"] = "http://%s:%s" % (
            local_ip,
            os.environ.get("PORT", "5000"),
        )
    return metadata


def _combined_log_lines(env: dict, *, limit: int = 80) -> list[str]:
    """Newest-first onboard log lines to piggyback to DMZ."""
    lines: list[str] = []
    log_buffer = env.get("log_buffer") if isinstance(env, dict) else None
    if isinstance(log_buffer, dict):
        raw_lines = log_buffer.get("lines")
        if isinstance(raw_lines, list):
            lines.extend(str(line) for line in raw_lines if isinstance(line, str))
    lines.extend(get_recent_log_messages(limit))

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        clean = line.replace("\r", " ").replace("\n", " ").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean[:500])
        if len(out) >= limit:
            break
    return out


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

        from common.zone_auth import HEADER_SIGNATURE, HEADER_TIMESTAMP, HEADER_ZONE

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
        logger.exception(
            "sign failed unexpectedly (key was loaded at startup)%s",
            format_kv(error=str(e)),
        )
        return {}


def get_json(
    url: str,
    extra_headers: Optional[dict] = None,
    *,
    timeout: Optional[float] = None,
) -> Tuple[jsonT, bool]:
    logger.debug("get request%s", format_kv(url=url))
    headers = {"Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    r = requests.get(
        url,
        headers=headers,
        timeout=timeout if timeout is not None else ONBOARD_HTTP_TIMEOUT_SECS,
    )
    logger.info("get response%s", format_kv(url=url, status=r.status_code))
    if not r.ok:
        return (r.text, False)
    if not r.text:
        return ({}, True)
    try:
        return (r.json(), True)
    except Exception:
        return (f"unexpected string response: {r.text}", False)


def post_json(
    url: str,
    body: dict,
    extra_headers: Optional[dict] = None,
    *,
    timeout: Optional[float] = None,
) -> Tuple[jsonT, bool, int]:
    """POST JSON; return (parsed-or-raw body, ok, status_code).

    status_code is 0 on transport failure (caught by caller). Callers use status_code to
    distinguish HTTP error classes — in particular 401-with-no-headers (we forgot to sign)
    from 401-with-headers (DMZ rejected the signature).
    """
    logger.debug("post request%s", format_kv(url=url))
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    r = requests.post(
        url,
        json=body,
        headers=headers,
        timeout=timeout if timeout is not None else ONBOARD_HTTP_TIMEOUT_SECS,
    )
    logger.info("post response%s", format_kv(url=url, status=r.status_code))
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
            "(see the selected hardware backend compose file and thermo/KEYS-AND-CERTS.md)."
        )
    if status == 403:
        return "DMZ accepted the signature but forbade the action (403). Check zone allowlist."
    if status >= 500:
        return f"DMZ server error ({status}); not our config — see DMZ logs."
    return f"DMZ returned HTTP {status}."


def poll_once() -> bool:
    """One bidirectional sync round. Convergence relies on each side's strictly-newer
    ``created_dt`` gate; no separate "authoritative command" push is needed."""
    try:
        # 1/3: pull onboard's current sensors AND last-applied command (with created_dt).
        env, ok_get = get_json(readfrom)
        if not ok_get:
            logger.error(
                "get from onboard failed: aborting poll%s", format_kv(error=env)
            )
            return False
        logger.debug(
            "poll_once 1/3 ONBOARD -> twoway env+command%s", format_kv(env=env)
        )

        # 2/3: POST {sensors, command?} to DMZ. DMZ replaces its stored command only when
        # ours is strictly newer than what it already has (logged on DMZ side as
        # accepted/obsolete); response contains DMZ's current authoritative zone state.
        dmz_body = _env_to_dmz_body(env)
        body_bytes = json.dumps(dmz_body).encode()
        extra = _sign_headers("POST", DMZ_SIGN_PATH, body_bytes, ZONE_NAME)
        signed = bool(extra)
        res, ok_dmz, status = post_json(
            dmz,
            dmz_body,
            extra_headers=extra if extra else None,
            timeout=DMZ_HTTP_TIMEOUT_SECS,
        )
        logger.debug(
            "poll_once 2/3 twoway -> DMZ returning zone state%s",
            format_kv(res=res, ok_dmz=ok_dmz, status=status),
        )
        if not ok_dmz:
            logger.error(
                "post to DMZ failed: aborting poll%s",
                format_kv(
                    status=status,
                    signed=signed,
                    hint=_explain_dmz_failure(status, signed),
                    error=res,
                ),
            )
            return False

        # 3/3: POST DMZ's zone state to onboard /daikin. Onboard applies the command only
        # when its created_dt is strictly newer than what onboard already tracks (logged
        # on onboard side as accepted/obsolete). No post-step fixup: convergence is
        # symmetric across both gates.
        write_res, ok_write, _wstatus = post_json(writeto, res)
        if not ok_write:
            logger.error(
                "post to onboard failed: aborting poll%s",
                format_kv(error=write_res, res=res),
            )
            return False
        logger.debug(
            "poll_once 3/3 twoway -> ONBOARD returning apply result%s",
            format_kv(writeto=writeto, res=write_res, ok_write=ok_write),
        )
    except Exception as e:
        logger.exception("failed%s", format_kv(error=str(e)))
        return False
    return True


def poll_forever() -> None:
    logger.info("twoway poll forever start")
    slp = PERIOD_SECS
    next_poll_not_before = time.monotonic()
    while True:
        now = time.monotonic()
        wait_secs = max(0.0, next_poll_not_before - now)
        if wait_secs > 0:
            logger.info(
                "sleep before poll%s",
                format_kv(
                    sleep_secs=round(wait_secs, 3),
                    min_period_secs=slp,
                ),
            )
            time.sleep(wait_secs)
        poll_started_at = time.monotonic()
        ok = poll_once()
        if ok:
            slp = PERIOD_SECS
        else:
            slp = min(PERIOD_MAX_SECS, slp + 1)
        # Enforce minimum delay between poll starts. If the previous poll consumed most
        # (or all) of slp, we do little/no extra sleeping on the next loop.
        next_poll_not_before = poll_started_at + slp


def main() -> None:
    """Run the twoway polling loop for this hardware target."""
    global PERIOD_SECS
    if os.environ.get("ENV") in ["DOCKERTEST"]:
        PERIOD_SECS = 0.1
        logger.info("twoway dockertest override%s", format_kv(period_secs=PERIOD_SECS))
    poll_forever()


logger.info("enter")
if __name__ == "__main__":
    main()
logger.info("exit")
