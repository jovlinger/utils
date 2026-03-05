"""
Test driver for docker-compose

hint. After a run, do
> docker compose logs testdriver to get the test logs.
"""

import socket

import pytest
import requests
import time

b = "http://dmz:5000"
o = "http://onboard:5000"


def _in_docker() -> bool:
    """True if dmz hostname resolves (docker-compose network)."""
    try:
        socket.gethostbyname("dmz")
        return True
    except socket.gaierror:
        return False

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

    def issue_command(self, zone, *, lolidk):
        return post_json(f"{b}/zone/{self.name}/command", {"lolidk": lolidk})

    def all_backends(self):
        r = requests.get(f"{b}/zones")
        assert r.status_code == 200
        return r.json()


def reset_dmz():
    print("reset dmz")
    r = requests.post(f"{b}/test_reset", json={"commands": {}, "sensors": {}})
    assert r.status_code == 200


@pytest.mark.skipif(not _in_docker(), reason="requires docker-compose (dmz hostname)")
def test_onboard_help():
    """Tests that we can reach onboard, and that the app is running"""
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
