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
from common import jsonT, log, log_debug, log_error


def info(msg: str, **kwargs) -> None:
    """Log via common.log (same format as app)."""
    log("twoway", msg, **kwargs)


def err(msg: str, **kwargs) -> None:
    """Log at ERROR (same kwargs style as info)."""
    log_error("twoway", msg, **kwargs)


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
    signing_enabled=bool(ZONE_PRIVATE_KEY and ZONE_NAME),
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
    """Add Ed25519 signature headers if ZONE_PRIVATE_KEY is set."""
    if not ZONE_PRIVATE_KEY or not zonename:
        return {}
    try:
        from zone_auth import (
            sign_request,
            HEADER_SIGNATURE,
            HEADER_TIMESTAMP,
            HEADER_ZONE,
        )

        sig, ts, _ = sign_request(method, path, body, zonename, ZONE_PRIVATE_KEY)
        return {HEADER_SIGNATURE: sig, HEADER_TIMESTAMP: ts, HEADER_ZONE: zonename}
    except Exception as e:
        info("sign failed", error=str(e))
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
) -> Tuple[jsonT, bool]:
    dbg("post request", url=url)
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    r = requests.post(url, json=body, headers=headers, timeout=TIMEOUT_SECS)
    info("post response", url=url, status=r.status_code)
    if r.status_code != 200:
        return (r.text, False)
    try:
        return (r.json(), True)
    except Exception:
        return (f"unexpected string response: {r.text}", False)


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
        res, ok_dmz = post_json(dmz, dmz_body, extra_headers=extra if extra else None)
        dbg(f"poll_once dmz -> twoway", res=res, ok_dmz=ok_dmz)
        if not ok_dmz:
            err("post to DMZ failed: aborting poll", error=res)
            return False

        # POST zone state to onboard /daikin; app.py owns conversion to State
        write_res, ok_write = post_json(writeto, res)
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
