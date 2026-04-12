"""Tests for manage.py CLI helpers (DMZ_URL validation)."""

from __future__ import annotations

import contextlib
import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import manage  # noqa: E402


class UpdatezoneNoKvTest(unittest.TestCase):
    def test_zone_without_kv_prints_help_then_state_on_stdout(self) -> None:
        with patch.dict(os.environ, {"DMZ_URL": "http://127.0.0.1:9"}, clear=False):
            fake_zones = {
                "z1": {
                    "command": {"power": True, "mode": "HEAT", "temp_c": 22},
                    "sensors": {"temp_centigrade": 20.0},
                }
            }
            with patch.object(manage, "_request_json", return_value=(200, fake_zones)):
                err = io.StringIO()
                out = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                    code = manage._cmd_updatezone("z1", [])
                self.assertEqual(code, 0)
                self.assertIn("updatezone <zone>", err.getvalue())
                self.assertIn("HEAT", out.getvalue())
                self.assertIn("temp_centigrade", out.getvalue())

    def test_zone_missing_returns_1_after_help(self) -> None:
        with patch.dict(os.environ, {"DMZ_URL": "http://127.0.0.1:9"}, clear=False):
            with patch.object(manage, "_request_json", return_value=(200, {})):
                err = io.StringIO()
                out = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                    code = manage._cmd_updatezone("missing", [])
                self.assertEqual(code, 1)
                self.assertIn("zone not found", err.getvalue())
                self.assertEqual(out.getvalue(), "")

    def test_get_zones_error_after_help_returns_1(self) -> None:
        with patch.dict(os.environ, {"DMZ_URL": "http://127.0.0.1:9"}, clear=False):
            with patch.object(
                manage, "_request_json", return_value=(401, {"error": "nope"})
            ):
                err = io.StringIO()
                out = io.StringIO()
                with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
                    code = manage._cmd_updatezone("z1", [])
                self.assertEqual(code, 1)
                self.assertIn("updatezone <zone>", err.getvalue())
                self.assertIn("nope", err.getvalue())
                self.assertEqual(out.getvalue(), "")


class UpdatezoneHelpTest(unittest.TestCase):
    def test_help_includes_onboard_state_example(self) -> None:
        msg = manage._updatezone_help_message()
        self.assertIn("updatezone <zone>", msg)
        self.assertIn('"comfort"', msg)
        self.assertIn('"half_c"', msg)
        self.assertIn('"mode"', msg)
        self.assertIn('"timer_on_minutes"', msg)
        self.assertIn("HEAT", msg)

    def test_state_example_matches_to_json(self) -> None:
        d = manage._onboard_state_example_dict()
        self.assertEqual(d["mode"], "HEAT")
        self.assertEqual(d["power"], True)
        self.assertIn("half_c", d)
        self.assertIn("timer_on_active", d)


class DmzBaseUrlTest(unittest.TestCase):
    def _stderr_on_dmz_base(self) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            try:
                manage._dmz_base()
            except SystemExit as exc:
                return int(exc.code or 0), buf.getvalue()
        return 0, buf.getvalue()

    def test_missing_env_same_tone_as_empty(self) -> None:
        with patch.dict(os.environ, {"DMZ_URL": ""}, clear=False):
            code, err = self._stderr_on_dmz_base()
        self.assertEqual(code, 2)
        self.assertIn("DMZ_URL is not set", err)

    def test_host_port_without_scheme_gets_http_prefix(self) -> None:
        with patch.dict(
            os.environ,
            {"DMZ_URL": "192.168.88.200:5000"},
            clear=False,
        ):
            base = manage._dmz_base()
        self.assertEqual(base, "http://192.168.88.200:5000")

    def test_hostname_only_without_scheme_gets_http_prefix(self) -> None:
        with patch.dict(os.environ, {"DMZ_URL": "dmz.local"}, clear=False):
            base = manage._dmz_base()
        self.assertEqual(base, "http://dmz.local")

    def test_invalid_base_url_rejected(self) -> None:
        # Slashes only → http:// with no host (urllib has nothing in netloc).
        with patch.dict(os.environ, {"DMZ_URL": "///"}, clear=False):
            code, err = self._stderr_on_dmz_base()
        self.assertEqual(code, 2)
        self.assertIn("not a valid base URL", err)

    def test_accepts_http_base(self) -> None:
        with patch.dict(
            os.environ,
            {"DMZ_URL": "http://192.168.88.200:5000"},
            clear=False,
        ):
            base = manage._dmz_base()
        self.assertEqual(base, "http://192.168.88.200:5000")

    def test_strips_trailing_slash(self) -> None:
        with patch.dict(
            os.environ,
            {"DMZ_URL": "http://dmz:5000/"},
            clear=False,
        ):
            base = manage._dmz_base()
        self.assertEqual(base, "http://dmz:5000")
