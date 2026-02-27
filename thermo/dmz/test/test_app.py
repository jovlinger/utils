"""DMZ app tests: unit tests and happy-path integration tests."""

from __future__ import annotations

import os
import sys
from unittest import TestCase

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app


def _pathget(d: dict, path: str):
    """Get nested dict value by dot-separated path, e.g. 'command.lolidk'."""
    for key in path.split("."):
        d = d.get(key, {}) if isinstance(d, dict) else d
    return d


class DMZTest(TestCase):
    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()

    def tearDown(self) -> None:
        self.ctx.pop()

    def post_200(self, c, url: str, json: dict) -> dict:
        res = c.post(url, json=json)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json() or {}

    def get_200(self, c, url: str) -> dict:
        res = c.get(url)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json() or {}

    def reset(
        self, c, commands: dict | None = None, sensors: dict | None = None
    ) -> None:
        self.post_200(
            c, "/test_reset", {"commands": commands or {}, "sensors": sensors or {}}
        )

    def test_update_sensors_and_command_multi_zone(self) -> None:
        """Multiple zones: update sensors/commands, verify last_access_dt and latest values."""
        with app.test_client() as c:
            self.reset(c)
            self.post_200(c, "/zone/z1/command", {"lolidk": "what"})
            self.post_200(c, "/zone/z1/sensors", {"temp_centigrade": 11.45})
            self.post_200(
                c,
                "/zone/z2/sensors",
                {"temp_centigrade": 21.34, "humid_percent": 99.99},
            )
            js12 = self.post_200(c, "/zone/z1/command", {"lolidk": "make it so"})
            self.post_200(c, "/zone/z3/command", {"lolidk": "who"})

            js13 = self.post_200(c, "/zone/z1/sensors", {"temp_centigrade": 13.34})

            self.assertNotEqual(
                js12["command"]["last_access_dt"],
                js13["command"]["last_access_dt"],
                "Expected access times to be updated on /zone/ endpoint",
            )
            self.assertEqual("make it so", js13["command"]["lolidk"])
            self.assertEqual(13.34, js13["sensors"]["temp_centigrade"])

            js = self.get_200(c, "/zones")
            self.assertEqual(["z1", "z2", "z3"], sorted(js.keys()))
            self.assertEqual(js13, js["z1"])

    def test_empty_command_overwrites_then_new_command(self) -> None:
        """POST empty command clears lolidk; subsequent command restores it."""
        with app.test_client() as c:
            self.reset(c)
            self.post_200(c, "/zone/z1/command", {"lolidk": "what"})
            self.post_200(c, "/zone/z1/command", {})
            js = self.get_200(c, "/zones")
            self.assertEqual("", _pathget(js["z1"], "command.lolidk"))
            self.post_200(c, "/zone/z1/command", {"lolidk": "who"})
            js = self.get_200(c, "/zones")
            self.assertEqual("who", _pathget(js["z1"], "command.lolidk"))


class HappyPathOnboardTest(TestCase):
    """
    Simulate onboard instances (via twoway) reading commands and updating sensors.
    Each zone POSTs sensors to /zone/<name>/sensors and receives back the latest command.
    """

    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        self._reset()

    def tearDown(self) -> None:
        self.ctx.pop()

    def _reset(self) -> None:
        with app.test_client() as c:
            c.post("/test_reset", json={"commands": {}, "sensors": {}})

    def _onboard_post_sensors(
        self, c, zone: str, temp: float, humid: float | None = None
    ) -> dict:
        """Simulate onboard zone posting sensor data; returns zone state (command + sensors)."""
        body: dict = {"temp_centigrade": temp}
        if humid is not None:
            body["humid_percent"] = humid
        return c.post(f"/zone/{zone}/sensors", json=body).get_json() or {}

    def _post_200(self, c, url: str, json: dict) -> dict:
        res = c.post(url, json=json)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json() or {}

    def _get_200(self, c, url: str) -> dict:
        res = c.get(url)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json() or {}

    def test_onboard_zones_poll_sensors_receive_commands(self) -> None:
        """
        External client sets command for z1. Onboard z1 posts sensors, receives command.
        Onboard z2 posts sensors, has no command. External client sets command for z2.
        """
        with app.test_client() as c:
            # External client sets command for zone z1 (before any onboard has polled)
            self._post_200(c, "/zone/z1/command", {"lolidk": "heat_on"})

            # Onboard z1 (twoway) posts sensors, gets back the command
            r1 = self._onboard_post_sensors(c, "z1", 19.5, 45.0)
            self.assertEqual(r1["command"]["lolidk"], "heat_on")
            self.assertEqual(r1["sensors"]["temp_centigrade"], 19.5)
            self.assertEqual(r1["sensors"]["humid_percent"], 45.0)

            # Onboard z2 posts sensors; no command yet
            r2 = self._onboard_post_sensors(c, "z2", 21.0)
            self.assertTrue(
                r2.get("command") is None or r2.get("command", {}).get("lolidk") == ""
            )

            # External client sets command for z2
            self._post_200(c, "/zone/z2/command", {"lolidk": "cool_22"})

            # Onboard z2 posts again, now receives command
            r3 = self._onboard_post_sensors(c, "z2", 21.2)
            self.assertEqual(r3["command"]["lolidk"], "cool_22")

    def test_onboard_multiple_zones_independent(self) -> None:
        """Multiple onboard instances: each zone's sensors and commands are independent."""
        with app.test_client() as c:
            self._post_200(c, "/zone/living/command", {"lolidk": "heat_22"})
            self._post_200(c, "/zone/bedroom/command", {"lolidk": "off"})

            living = self._onboard_post_sensors(c, "living", 20.1, 50.0)
            bedroom = self._onboard_post_sensors(c, "bedroom", 18.5, 55.0)

            self.assertEqual(living["command"]["lolidk"], "heat_22")
            self.assertEqual(bedroom["command"]["lolidk"], "off")
            self.assertEqual(living["sensors"]["temp_centigrade"], 20.1)
            self.assertEqual(bedroom["sensors"]["temp_centigrade"], 18.5)


class HappyPathExternalClientTest(TestCase):
    """
    Simulate external client: reading all zone state (GET /zones) and updating commands
    (POST /zone/<name>/command).
    """

    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        self._reset()

    def tearDown(self) -> None:
        self.ctx.pop()

    def _reset(self) -> None:
        with app.test_client() as c:
            c.post("/test_reset", json={"commands": {}, "sensors": {}})

    def _post_200(self, c, url: str, json: dict) -> dict:
        res = c.post(url, json=json)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json() or {}

    def _get_200(self, c, url: str) -> dict:
        res = c.get(url)
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        return res.get_json() or {}

    def test_external_client_reads_state_updates_commands(self) -> None:
        """
        Onboard zones have posted sensors. External client GETs /zones, sees state.
        External client POSTs commands. Next onboard poll will receive them.
        """
        with app.test_client() as c:
            # Simulate onboard zones having posted sensors
            c.post(
                "/zone/z1/sensors",
                json={"temp_centigrade": 20.0, "humid_percent": 40.0},
            )
            c.post("/zone/z2/sensors", json={"temp_centigrade": 22.5})

            # External client reads all zones
            zones = self._get_200(c, "/zones")
            self.assertEqual(set(zones.keys()), {"z1", "z2"})
            self.assertEqual(zones["z1"]["sensors"]["temp_centigrade"], 20.0)
            self.assertEqual(zones["z2"]["sensors"]["temp_centigrade"], 22.5)

            # External client sets commands
            self._post_200(c, "/zone/z1/command", {"lolidk": "heat_21"})
            self._post_200(c, "/zone/z2/command", {"lolidk": "cool_24"})

            # Verify via GET (external client view)
            zones = self._get_200(c, "/zones")
            self.assertEqual(zones["z1"]["command"]["lolidk"], "heat_21")
            self.assertEqual(zones["z2"]["command"]["lolidk"], "cool_24")

    def test_external_client_full_cycle(self) -> None:
        """
        Full cycle: onboard posts -> external reads -> external sets command ->
        onboard posts again and receives command.
        """
        with app.test_client() as c:
            # Onboard z1 posts sensors
            c.post("/zone/kitchen/sensors", json={"temp_centigrade": 19.0})

            # External client reads, sets command
            zones = self._get_200(c, "/zones")
            self.assertIn("kitchen", zones)
            self._post_200(c, "/zone/kitchen/command", {"lolidk": "heat_20"})

            # Simulate onboard kitchen posting again (twoway poll)
            r = c.post(
                "/zone/kitchen/sensors",
                json={"temp_centigrade": 19.5, "humid_percent": 48.0},
            ).get_json()
            self.assertEqual(r["command"]["lolidk"], "heat_20")
            self.assertEqual(r["sensors"]["temp_centigrade"], 19.5)
