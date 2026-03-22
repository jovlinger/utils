"""
Smoke tests: HTTP against a running DMZ (not Flask test_client).

Run: from repo venv, `DMZ_URL=http://host:port pytest -v -s test_smoke.py`
Or: `./smoketest/run.sh` (defaults to local Docker on 8080).

Auth model (smoketest vs production)
------------------------------------
- **OAuth (human / “external client” paths):** `/zones`, `/debug/logs`, and
  `POST /zone/<name>/command` use OAuth when `GOOGLE_CLIENT_ID` is set: a
  logged-in browser session (`ALLOWED_EMAIL`) is required unless the request
  carries a valid zone machine signature (see below). If `GOOGLE_CLIENT_ID` is
  **unset** (typical container/smoke image), OAuth is off — no session cookie, no
  redirect. Smoketests hit those endpoints with plain JSON and succeed.

- **Zone machine auth:** When `ZONE_PUBLIC_KEY` / `ZONE_PUBLIC_KEY_PATH` is set,
  `POST /zone/<name>/sensors` always requires a valid signature. The same applies
  to `POST /zone/<name>/command` when the client sends `X-Zone-Signature`, and
  to `GET /zones` and `GET /debug/logs` (empty body). If the public key is
  **unset**, verification is skipped for those checks. Smoketests post sensors
  without signing headers.

  **Real usage:** set the zone public key; Twoway, `manage.py`, or the device
  must send `X-Zone-Signature`, `X-Zone-Timestamp`, `X-Zone-Name` per
  `zone_auth.py`. With the public key set and OAuth off, unsigned `GET /zones`
  or `POST .../command` returns 401 unless a browser session is used when OAuth
  is enabled.

- **`POST /test_reset`:** intentionally **unauthenticated** (testing only).
  Do not expose DMZ to the internet with this route reachable.

“History” in these tests is **`GET /debug/logs`**: in-memory ring buffer of
`{method, path, status, ts}` (max 500). Per-zone command/sensor **lists** exist
server-side but only the **latest** state is returned from `/zones`; there is
no history API for past IR readings yet.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Set

import pytest
import requests

BASE: str = os.environ.get("DMZ_URL", "http://127.0.0.1:8080").rstrip("/")

logger = logging.getLogger("dmz.smoke")

_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


@pytest.fixture(scope="module", autouse=True)
def _log_base_url() -> None:
    logger.info("DMZ_URL (BASE) = %s", BASE)


@pytest.fixture
def http() -> requests.Session:
    s = requests.Session()
    s.headers.update(_JSON_HEADERS)
    return s


def _post_json(session: requests.Session, path: str, body: Dict[str, Any]) -> Any:
    url = f"{BASE}{path}"
    logger.info("POST %s body_keys=%s", url, list(body.keys()) if isinstance(body, dict) else "?")
    r = session.post(url, json=body, timeout=30)
    logger.info("POST %s -> %s len=%s", path, r.status_code, len(r.content))
    assert r.status_code == 200, (r.status_code, r.text)
    if not r.content:
        return None
    return r.json()


def _get_json(session: requests.Session, path: str) -> Any:
    url = f"{BASE}{path}"
    logger.info("GET %s", url)
    r = session.get(url, timeout=30)
    logger.info("GET %s -> %s len=%s", path, r.status_code, len(r.content))
    assert r.status_code == 200, (r.status_code, r.text)
    return r.json()


def _paths_from_access_log(logs: List[Dict[str, Any]]) -> List[str]:
    return [str(e.get("path", "")) for e in logs]


def test_smoke_reset_and_zones_empty(http: requests.Session) -> None:
    logger.info("case: reset state, expect empty /zones")
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    js = _get_json(http, "/zones")
    assert js == {}
    logger.info("ok: /zones is empty dict")


def test_smoke_command_round_trip(http: requests.Session) -> None:
    logger.info("case: post command, read back via /zones")
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    _post_json(http, "/zone/z1/command", {"lolidk": "smoke"})
    js = _get_json(http, "/zones")
    assert "z1" in js
    assert js["z1"]["command"]["lolidk"] == "smoke"
    logger.info("ok: z1 command lolidk=smoke")


def test_smoke_debug_logs(http: requests.Session) -> None:
    logger.info("case: GET /debug/logs")
    r = http.get(f"{BASE}/debug/logs", timeout=30)
    logger.info("/debug/logs -> %s len=%s", r.status_code, len(r.content))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "logs" in body
    assert isinstance(body["logs"], list)
    n = len(body["logs"])
    logger.info("ok: debug logs list length=%s", n)


def test_smoke_multi_zone_sensor_updates(http: requests.Session) -> None:
    logger.info("case: several zones post sensors, /zones shows each latest")
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    _post_json(http, "/zone/kitchen/sensors", {"temp_centigrade": 19.0})
    _post_json(http, "/zone/bedroom/sensors", {"temp_centigrade": 17.5, "humid_percent": 42.0})
    _post_json(http, "/zone/kitchen/sensors", {"temp_centigrade": 19.5})
    js = _get_json(http, "/zones")
    assert set(js.keys()) == {"bedroom", "kitchen"}
    assert js["kitchen"]["sensors"]["temp_centigrade"] == 19.5
    assert js["bedroom"]["sensors"]["temp_centigrade"] == 17.5
    assert js["bedroom"]["sensors"]["humid_percent"] == 42.0
    logger.info("ok: multi-zone sensor snapshots")


def test_smoke_multiple_external_command_clients(http: requests.Session) -> None:
    """Simulate two browsers/sessions posting commands (no shared cookies needed when OAuth off)."""
    logger.info("case: two sessions, commands to different zones")
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    _post_json(http, "/zone/a/sensors", {"temp_centigrade": 20.0})
    _post_json(http, "/zone/b/sensors", {"temp_centigrade": 21.0})

    alice = requests.Session()
    alice.headers.update(_JSON_HEADERS)
    bob = requests.Session()
    bob.headers.update(_JSON_HEADERS)

    _post_json(alice, "/zone/a/command", {"lolidk": "heat_20"})
    _post_json(bob, "/zone/b/command", {"lolidk": "cool_22"})

    js = _get_json(http, "/zones")
    assert js["a"]["command"]["lolidk"] == "heat_20"
    assert js["b"]["command"]["lolidk"] == "cool_22"
    assert js["a"]["sensors"]["temp_centigrade"] == 20.0
    assert js["b"]["sensors"]["temp_centigrade"] == 21.0
    logger.info("ok: two clients, two zones")


def test_smoke_access_log_history(http: requests.Session) -> None:
    """After a deterministic request sequence, access log should mention those paths."""
    logger.info("case: /debug/logs reflects recent HTTP paths")
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    _post_json(http, "/zone/logtest-a/sensors", {"temp_centigrade": 1.0})
    _post_json(http, "/zone/logtest-b/sensors", {"temp_centigrade": 2.0})
    _post_json(http, "/zone/logtest-a/command", {"lolidk": "x"})
    _get_json(http, "/zones")

    body = _get_json(http, "/debug/logs")
    paths: Set[str] = set(_paths_from_access_log(body["logs"]))
    required = {
        "/test_reset",
        "/zone/logtest-a/sensors",
        "/zone/logtest-b/sensors",
        "/zone/logtest-a/command",
        "/zones",
        "/debug/logs",
    }
    missing = required - paths
    assert not missing, f"access log missing paths: {missing}; have sample {list(paths)[:15]}"
    logger.info("ok: access log contains expected paths")
