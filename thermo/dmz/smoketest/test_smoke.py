"""
Smoke tests: HTTP against a running DMZ container (not Flask test_client).

Run via smoketest/run.sh (build image, docker run, then pytest this file).
"""

from __future__ import annotations

import os
from typing import Any, Dict

import pytest
import requests

BASE: str = os.environ.get("DMZ_URL", "http://127.0.0.1:8080").rstrip("/")

_JSON_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


@pytest.fixture
def http() -> requests.Session:
    s = requests.Session()
    s.headers.update(_JSON_HEADERS)
    return s


def _post_json(session: requests.Session, path: str, body: Dict[str, Any]) -> Any:
    r = session.post(f"{BASE}{path}", json=body, timeout=30)
    assert r.status_code == 200, (r.status_code, r.text)
    if not r.content:
        return None
    return r.json()


def test_smoke_reset_and_zones_empty(http: requests.Session) -> None:
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    r = http.get(f"{BASE}/zones", timeout=30)
    assert r.status_code == 200, r.text
    assert r.json() == {}


def test_smoke_command_round_trip(http: requests.Session) -> None:
    _post_json(http, "/test_reset", {"commands": {}, "sensors": {}})
    _post_json(http, "/zone/z1/command", {"lolidk": "smoke"})
    r = http.get(f"{BASE}/zones", timeout=30)
    assert r.status_code == 200, r.text
    js = r.json()
    assert "z1" in js
    assert js["z1"]["command"]["lolidk"] == "smoke"


def test_smoke_debug_logs(http: requests.Session) -> None:
    r = http.get(f"{BASE}/debug/logs", timeout=30)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "logs" in body
    assert isinstance(body["logs"], list)
