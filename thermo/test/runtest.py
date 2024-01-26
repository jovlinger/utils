"""
Test driver for docker-compose
"""

import requests
import pytest

def test_simple():
    """Simple first test. No state is changed."""
    res_o = requests.get("http://onboard:5000/help")
    print(f"{res_o.json}")

    res_d = requests.get("http://onboard:5000/help")
    print(f"{res_o.json}")




