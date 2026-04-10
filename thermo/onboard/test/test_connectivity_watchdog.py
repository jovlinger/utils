"""Unit tests for connectivity_watchdog helpers (no Docker)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from connectivity_watchdog import (
    check_http_reachable,
    decode_pi_throttled,
    parse_measure_temp_line,
    parse_throttled_line,
    tail_file,
    trim_old_incidents,
    write_incident_bundle,
)


class TestTailFile(unittest.TestCase):
    def test_tail_respects_max_lines(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.log"
            lines = [f"line{i}" for i in range(100)]
            p.write_text("\n".join(lines), encoding="utf-8")
            out = tail_file(str(p), max_lines=5, max_bytes=100000)
            self.assertIn("line99", out)
            self.assertNotIn("line94", out)

    def test_missing_file(self) -> None:
        out = tail_file("/nonexistent/path/twoway.log")
        self.assertIn("missing", out)


class TestIncidents(unittest.TestCase):
    def test_trim_keeps_newest(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            dump = Path(d)
            for i in range(5):
                (dump / f"incident-2026010{i}-120000Z.txt").write_text("x", encoding="utf-8")
            trim_old_incidents(dump, keep=2)
            remaining = sorted(dump.glob("incident-*.txt"))
            self.assertEqual(len(remaining), 2)

    def test_write_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            dump = Path(d)
            path = write_incident_bundle("hello", dump, keep=10)
            self.assertTrue(path.is_file())
            self.assertEqual(path.read_text(encoding="utf-8"), "hello")


class TestPiThrottleParse(unittest.TestCase):
    def test_parse_throttled(self) -> None:
        self.assertEqual(parse_throttled_line("throttled=0x50000\n"), 0x50000)
        self.assertIsNone(parse_throttled_line("no hex"))

    def test_parse_temp(self) -> None:
        self.assertAlmostEqual(
            parse_measure_temp_line("temp=42.3'C\n") or 0.0, 42.3, places=3
        )

    def test_decode_flags(self) -> None:
        # bit 18: throttling has occurred
        self.assertIn(
            "throttled_occurred",
            decode_pi_throttled(1 << 18),
        )
        self.assertEqual(decode_pi_throttled(0), "none")


class TestHttpReachable(unittest.TestCase):
    @patch("connectivity_watchdog.requests.get")
    def test_ok_on_404(self, mock_get: MagicMock) -> None:
        r = MagicMock()
        r.status_code = 404
        mock_get.return_value = r
        ok, detail = check_http_reachable("http://example.test/", 1.0)
        self.assertTrue(ok)
        self.assertIn("404", detail)

    @patch("connectivity_watchdog.requests.get")
    def test_fail_on_timeout(self, mock_get: MagicMock) -> None:
        import requests

        mock_get.side_effect = requests.Timeout("nope")
        ok, detail = check_http_reachable("http://example.test/", 1.0)
        self.assertFalse(ok)
        self.assertIn("nope", detail)


if __name__ == "__main__":
    unittest.main()
