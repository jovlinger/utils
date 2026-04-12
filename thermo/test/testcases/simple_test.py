"""
Test driver for docker-compose

hint. After a run, do
> docker compose logs testdriver to get the test logs.
"""

import os
import socket
import time

import pytest
import requests

b = os.environ.get("DMZ_URL", "http://dmz:8080")
o = os.environ.get("ONBOARD_URL", "http://onboard:5000")


def _in_docker() -> bool:
    """True if dmz hostname resolves (docker-compose network)."""
    try:
        socket.gethostbyname("dmz")
        return True
    except socket.gaierror:
        return False


def _wait_for(url: str, *, timeout_s: float = 10.0) -> None:
    """Wait until GET url returns a 2xx/3xx or timeout."""
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            r = requests.get(url, timeout=1)
            if r.ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for {url}")

name_supply = ["bob", "jill", "jack", "annie", "mark", "mary", "paul", "stella"]

JSON = "JSON data type"


def post_json(url, body) -> JSON:
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    r = requests.post(url, json=body, headers=headers)
    assert r.status_code == 200
    return r.json()


class Zone:
    def __init__(self):
        pass

    def set_fake_readings(self, temp, humid):
        return post_json(
            f"{o}/test/inject_readings",
            {"temp_centigrade": temp, "humid_percent": humid},
        )


class External:
    def __init__(self, name="zoneymczoneface"):
        self.name = name

    def issue_command(self, zone, *, command: dict):
        return post_json(f"{b}/zone/{self.name}/command", command)

    def all_backends(self):
        r = requests.get(f"{b}/zones")
        assert r.status_code == 200
        return r.json()


def reset_dmz():
    print("reset dmz")
    _wait_for(f"{b}/zones", timeout_s=15.0)
    r = requests.post(f"{b}/test_reset", json={"commands": {}, "sensors": {}})
    assert r.status_code == 200


@pytest.mark.skipif(not _in_docker(), reason="requires docker-compose (dmz hostname)")
def test_onboard_help():
    """Tests that we can reach onboard, and that the app is running"""
    _wait_for(f"{o}/help", timeout_s=15.0)
    res_o = requests.get(f"{o}/help")
    js_o = res_o.json()
    assert "msg" in js_o
    # this is not very good, but frankly unlikely to change often
    assert "help -> this message" in js_o["msg"]


@pytest.mark.skipif(not _in_docker(), reason="requires docker-compose (dmz hostname)")
def test_dmz_backend():
    """Simple first test."""
    reset_dmz()

    e1 = External()
    z1 = Zone()

    js = e1.all_backends()
    return
    assert js == {}, f"XXX json {js} != empty"

    print("set readings")
    z1.set_fake_readings(12, 34)
    print("Sleeping for side=effect")
    time.sleep(10)
    print("Sleept for side=effect")
