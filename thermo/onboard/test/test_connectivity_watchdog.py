"""Unit tests for connectivity_watchdog helpers (no Docker)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from connectivity_watchdog import (
    check_http_reachable,
    decode_pi_throttled,
    parse_measure_temp_line,
    parse_throttled_line,
    tail_file,
    trim_old_incidents,
    write_incident_bundle,
)


def test_tail_respects_max_lines() -> None:
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.log"
        lines = [f"line{i}" for i in range(100)]
        p.write_text("\n".join(lines), encoding="utf-8")
        out = tail_file(str(p), max_lines=5, max_bytes=100000)
        assert "line99" in out
        assert "line94" not in out


def test_tail_missing_file() -> None:
    out = tail_file("/nonexistent/path/twoway.log")
    assert "missing" in out


def test_trim_keeps_newest() -> None:
    with tempfile.TemporaryDirectory() as d:
        dump = Path(d)
        for i in range(5):
            (dump / f"incident-2026010{i}-120000Z.txt").write_text("x", encoding="utf-8")
        trim_old_incidents(dump, keep=2)
        remaining = sorted(dump.glob("incident-*.txt"))
        assert len(remaining) == 2


def test_write_bundle() -> None:
    with tempfile.TemporaryDirectory() as d:
        dump = Path(d)
        path = write_incident_bundle("hello", dump, keep=10)
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == "hello"


def test_parse_throttled() -> None:
    assert parse_throttled_line("throttled=0x50000\n") == 0x50000
    assert parse_throttled_line("no hex") is None


def test_parse_temp() -> None:
    v = parse_measure_temp_line("temp=42.3'C\n") or 0.0
    assert v == pytest.approx(42.3, abs=0.001)


def test_decode_flags() -> None:
    assert "throttled_occurred" in decode_pi_throttled(1 << 18)
    assert decode_pi_throttled(0) == "none"


@patch("connectivity_watchdog.requests.get")
def test_http_ok_on_404(mock_get: MagicMock) -> None:
    r = MagicMock()
    r.status_code = 404
    mock_get.return_value = r
    ok, detail = check_http_reachable("http://example.test/", 1.0)
    assert ok
    assert "404" in detail


@patch("connectivity_watchdog.requests.get")
def test_http_fail_on_timeout(mock_get: MagicMock) -> None:
    mock_get.side_effect = requests.Timeout("nope")
    ok, detail = check_http_reachable("http://example.test/", 1.0)
    assert not ok
    assert "nope" in detail
