"""
Smoke tests: HTTP against a running DMZ container (not Flask test_client).

Run via smoketest/run.sh (build image, docker run, then pytest this file).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

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
