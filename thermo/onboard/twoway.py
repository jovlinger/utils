# this probably wants its own docker container

import json
from typing import Optional, Tuple
import os
import sys
import time
from urllib.parse import urlparse

import requests

# Same logging as app (configured in common)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import jsonT, log, log_debug, log_error


def info(msg: str, force: bool = False, **kwargs) -> None:
    """Log via common.log (same format as app)."""
    log("twoway", msg, **kwargs)


def err(msg: str, force: bool = False, **kwargs) -> None:
    """Log at ERROR (same kwargs style as info)."""
    log_error("twoway", msg, **kwargs)


def dbg(msg: str, force: bool = False, **kwargs) -> None:
    """Log at DEBUG (same kwargs style as info)."""
    log_debug("twoway", msg, **kwargs)


usage = """
<name> [-d] URL1 URL2 URL3

Options:

-d deamon mode: if present, fork and return

--

A small standalone binary that:

1. does a GET from URL 1
2. takes that and POSTs it to URL 2.
3. takes the response from URL 2 (if 200)
4. and POSTs it to URL 3.
5. take a breath, and repeat.

There will be rudimentary authorization for URL 2. None for URL 1 or 3. TBD

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

TIMEOUT_SECS: float = 10.0
PERIOD_SECS: float = 5.0
PERIOD_MAX_SECS: float = 60.0

info(
    "twoway config",
    readfrom=readfrom,
    dmz=dmz,
    writeto=writeto,
    dmz_sign_path=DMZ_SIGN_PATH,
    zone_name=ZONE_NAME or "(unset)",
    signing_enabled=bool(ZONE_PRIVATE_KEY and ZONE_NAME),
    timeout_secs=TIMEOUT_SECS,
    maxfail=MAXFAIL,
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


def _lolidk_to_state(lolidk: str) -> dict:
    """Convert DMZ lolidk string to onboard State JSON. E.g. heat_22 -> {power, mode, half_c}."""
    from heatpumpirctl import Mode, State

    lolidk = (lolidk or "").strip().lower()
    if not lolidk or lolidk == "off":
        return State().set_power(False).to_json()
    parts = lolidk.split("_")
    if len(parts) >= 2:
        try:
            temp = float(parts[1])
            mode_str = parts[0]
            mode_map = {
                "heat": Mode.HEAT,
                "cool": Mode.COOL,
                "dry": Mode.DRY,
                "auto": Mode.AUTO,
            }
            mode = mode_map.get(mode_str, Mode.HEAT)
            return State().set_power(True).set_mode(mode).set_temp(temp).to_json()
        except (ValueError, IndexError):
            pass
    return State().set_power(True).set_mode(Mode.AUTO).to_json()


def _zone_state_to_daikin(zone_state: dict) -> Optional[dict]:
    """Extract command from ZoneState and convert to onboard /daikin format."""
    cmd = zone_state.get("command") if isinstance(zone_state, dict) else None
    if not cmd or not isinstance(cmd, dict):
        return None
    lolidk = cmd.get("lolidk", "")
    if not lolidk:
        dbg("no lolidk in zone state: aborting post to onboard", error=zone_state)
        return None
    return {"command": _lolidk_to_state(lolidk)}


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
        return (f"unexpcted string response: {r.text}", False)


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
        return (f"unexpcted string response: {r.text}", False)


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
        if not ok_dmz:
            err("post to DMZ failed: aborting poll", error=res)
            return False

        # POST to onboard /daikin with command from zone state
        daikin_body = _zone_state_to_daikin(res)
        if daikin_body:
            _, ok_write = post_json(writeto, daikin_body)
            if not ok_write:
                err("post to onboard failed: aborting poll", error=daikin_body)
                return False
        else:
            info("no daikin body in zone state: no post to onboard")
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
            slp = max(PERIOD_MAX_SECS, slp + 1)


info("enter")
if __name__ == "__main__":
    if os.environ.get("ENV") in ["DOCKERTEST"]:
        PERIOD_SECS = 0.1
        info("twoway dockertest override", period_secs=PERIOD_SECS)
    poll_forever()
info("exit")
