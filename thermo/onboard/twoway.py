# this probably wants its own docker container

import json
from typing import Optional, Union
import os
import sys
import time
from urllib.parse import urlparse

import requests

# Same logging as app (configured in common)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import log


def out(msg: str, force: bool = False, **kwargs) -> None:
    """Log via common.log (same format as app)."""
    log("twoway", msg, **kwargs)


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

out("start", argv=sys.argv)

assert len(sys.argv) == 4

out("out ")

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
        out("sign failed", error=str(e))
        return {}


def post_json(url: str, body: dict, extra_headers: Optional[dict] = None) -> Union[dict, str]:
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body_bytes = json.dumps(body).encode()
    r = requests.post(url, json=body, headers=headers)
    assert r.status_code == 200, f"POST {url} -[{r.status_code}]-> {r.text}"
    try:
        return r.json()
    except Exception:
        return r.text


def poll_once() -> bool:
    try:
        res1 = requests.get(readfrom)
        out("r1 get", url=readfrom, status=res1.status_code)
        if not res1.ok:
            return False
        env = res1.json() if res1.text else {}
        sensors_body = _env_to_sensors(env)

        # POST to DMZ with optional machine auth
        dmz_body = sensors_body
        body_bytes = json.dumps(dmz_body).encode()
        path = _parsed_dmz.path or "/zone/default/sensors"
        extra = _sign_headers("POST", path, body_bytes, ZONE_NAME)
        res2 = post_json(dmz, dmz_body, extra_headers=extra if extra else None)
        out("r2 post dmz", url=dmz)

        # POST to onboard /daikin with command from zone state
        daikin_body = _zone_state_to_daikin(res2) if isinstance(res2, dict) else None
        if daikin_body:
            post_json(writeto, daikin_body)
        out("r3 post writeto", url=writeto)
    except Exception as e:
        out("failed", error=str(e))
        return False
    return True


MAXFAIL = 100
PERIOD_SECS = 5


def poll_forever() -> None:
    out("twoway poll forever start")
    attempts = MAXFAIL
    slp = PERIOD_SECS
    while attempts > 0:
        out(f"sleep: {slp}, attempts left {attempts}")
        time.sleep(slp)
        ok = poll_once()
        if ok:
            attempts = MAXFAIL
            slp = PERIOD_SECS
        else:
            attempts -= 1
            slp *= 1.5
    out("too many fail; exit")


out("enter")
if __name__ == "__main__":
    if os.environ.get("ENV") in ["DOCKERTEST"]:
        PERIOD_SECS = 0.1
    poll_forever()
out("exit")
