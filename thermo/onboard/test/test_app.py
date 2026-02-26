from unittest import TestCase
from unittest.mock import patch

# This BEFORE other imports on purpose, so that we are the root before
# others grab pointers to submodules.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import smbus_fake

sys.modules["smbus"] = smbus_fake

import app
import constants


def equalish(a, b) -> bool:
    if isinstance(a, dict):
        return equalish_dict(a, b)
    if isinstance(a, float):
        return equalish_float(a, b)
    return a == b


def equalish_dict(a: dict, b) -> bool:
    if not isinstance(b, dict):
        return False
    if len(a) != len(b):
        return False
    for k, va in a.items():
        vb = b[k]
        if not equalish(va, vb):
            return False
    return True


epsilon = 0.01


def equalish_float(a: float, b) -> bool:
    return abs(a - b) < epsilon


class AppTest(TestCase):
    # the help message is uniquely stupid to test, but it is a start
    def test_help(self):
        """Test using local call"""
        msg = app.help().get("msg")
        self.assertEqual(constants.help_msg, msg)

    def test_environment(self):
        """Environment returns temp/humidity from HTU21D (smbus_fake). Values match read_sensor formula."""
        res = app.environment()
        # smbus_fake returns (123, 34, 56) -> raw=(123*256+34)/65536 -> temp≈37.67, hum≈54.12
        want = {"temperature_centigrade": 37.67, "humidity_percent": 54.12}
        self.assertTrue(equalish(want, res))

    @patch("app.send_daikin_state", return_value=True)
    def test_daikin_sequence(self, mock_send):
        """Simple on / uptemp+fan3 / off sequence: POST commands, GET returns newest-first."""
        app.daikin_cmds.clear()
        client = app.app.test_client()

        # 1. Power on, HEAT 22°C
        r1 = client.post(
            "/daikin",
            json={
                "command": {"power": True, "mode": "HEAT", "temp_c": 22, "fan": "AUTO"}
            },
        )
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json["sent"])
        self.assertTrue(r1.json["command"]["power"])
        self.assertEqual(r1.json["command"]["mode"], "HEAT")
        self.assertEqual(r1.json["command"]["half_c"], 44)

        # 2. Uptemp to 23, fan F3
        r2 = client.post(
            "/daikin",
            json={
                "command": {"power": True, "mode": "HEAT", "temp_c": 23, "fan": "F3"}
            },
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json["command"]["half_c"], 46)
        self.assertEqual(r2.json["command"]["fan"], "F3")

        # 3. Power off
        r3 = client.post(
            "/daikin",
            json={
                "command": {"power": False, "mode": "HEAT", "temp_c": 23, "fan": "F3"}
            },
        )
        self.assertEqual(r3.status_code, 200)
        self.assertFalse(r3.json["command"]["power"])

        # GET returns newest first: off, fan3, on
        get_r = client.get("/daikin")
        self.assertEqual(len(get_r.json), 3)
        self.assertFalse(get_r.json[0]["command"]["power"])
        self.assertEqual(get_r.json[1]["command"]["fan"], "F3")
        self.assertTrue(get_r.json[2]["command"]["power"])
