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
        """Environment returns rounded temp/humidity from HTU21D (smbus_fake)."""
        with patch.dict(os.environ, {"ENV": "TEST"}, clear=False):
            # Reset singleton so this test always builds HTU21D with smbus_fake.
            app.HTU21D.instance = None
            res = app.environment()
        # smbus_fake yields ~37.67C and ~54.12%, endpoint contract rounds to 1 decimal.
        self.assertTrue(equalish(37.7, res.get("temperature_centigrade")))
        self.assertTrue(equalish(54.1, res.get("humidity_percent")))

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

    def test_manage_get_state(self):
        client = app.app.test_client()
        with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
            r = client.get("/manage", headers={"X-Manage-Token": "test-token"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("pid", r.json)
        self.assertIn("log_level", r.json)
        self.assertIn("fake_sensor", r.json)

    def test_manage_set_log_level(self):
        client = app.app.test_client()
        with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
            r = client.post(
                "/manage",
                json={"action": "set_log_level", "level": "debug"},
                headers={"X-Manage-Token": "test-token"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["level"], "DEBUG")

    def test_manage_inject_log(self):
        client = app.app.test_client()
        with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
            r = client.post(
                "/manage",
                json={"action": "inject_log", "level": "INFO", "message": "hello"},
                headers={"X-Manage-Token": "test-token"},
            )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["action"], "inject_log")
        self.assertEqual(r.json["message"], "hello")

    def test_manage_raise(self):
        client = app.app.test_client()
        with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
            r = client.post(
                "/manage",
                json={"action": "raise", "message": "boom"},
                headers={"X-Manage-Token": "test-token"},
            )
        self.assertEqual(r.status_code, 500)
