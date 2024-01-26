"""
Test driver for docker-compose

hint. After a run, do 
> docker compose logs testdriver to get the test logs.
"""

import requests


def test_simple():
    """Simple first test. No state is changed."""
    res_o = requests.get("http://onboard:5000/help")
    print(f"XXX Onboard: {res_o.text}")

    res_d = requests.get("http://dmz:5000/backends")
    print(f"XXX DMZ: {res_d.text}")

    js_o = res_o.json()
    print(f"XXX Onboard json {js_o}")
    js_d = res_d.json()
    print(f"XXX DMZ json {js_d}")



