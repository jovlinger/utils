"""Host tests for MicroPython debug HTTP builders (no board required)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

MP_DIR = Path(__file__).resolve().parents[1] / "mp"
sys.path.insert(0, str(MP_DIR))

import config  # noqa: E402
import httpdebug  # noqa: E402
from logring import LogRing  # noqa: E402
from main import DebugApp  # noqa: E402


def test_logring_newest_first_and_capacity() -> None:
    clock = {"t": 1000}

    def now() -> int:
        return clock["t"]

    ring = LogRing(capacity=3, boot_ms=1000, clock_ms=now)
    ring.add("a")
    clock["t"] = 1100
    ring.add("b")
    clock["t"] = 1200
    ring.add("c")
    clock["t"] = 1300
    ring.add("d")
    assert len(ring) == 3
    newest = ring.newest_first()
    assert newest[0].endswith(" d")
    assert newest[-1].endswith(" b")
    assert " a" not in " ".join(newest)


def test_healthz_shape_matches_debug_contract() -> None:
    app = DebugApp(local_ip="192.168.88.73")
    status, body = app.handle_path("/healthz")
    assert status == 200
    assert body["ok"] is True
    assert body["service"] == "onboard-app"
    assert body["hardware_backend"] == "esp32s3"
    assert body["runtime"] == "micropython"
    assert body["deployment"]["zone_name"] == config.ZONE_NAME
    assert body["deployment"]["backend"] == "esp32s3"
    assert body["deployment"]["ir_device"] == "gpio17"
    assert body["network"]["local_ip"] == "192.168.88.73"
    assert body["network"]["onboard_url"] == "http://192.168.88.73:5000"
    assert "uptime_seconds" in body["esp32s3"]
    assert body["log_buffer"]["capacity"] == config.LOG_CAPACITY
    assert body["log_buffer"]["returned"] >= 1
    # JSON-serializable for on-device json.dumps
    json.dumps(body)


def test_logs_and_gpio_routes() -> None:
    app = DebugApp()
    st, logs = app.handle_path("/logs")
    assert st == 200
    assert isinstance(logs["lines"], list)
    assert logs["path"] is None
    st, gpio = app.handle_path("/gpio")
    assert st == 200
    assert gpio["pullup_gpio"] == config.DEBUG_PULLUP_GPIO
    assert gpio["pulldown_gpio"] == config.DEBUG_PULLDOWN_GPIO


def test_unknown_path_404() -> None:
    app = DebugApp()
    st, body = app.handle_path("/nope")
    assert st == 404
    assert body["error"] == "not_found"


def test_parse_request_path() -> None:
    assert httpdebug.parse_request_path("GET /healthz HTTP/1.0\r\n") == "/healthz"
    assert httpdebug.parse_request_path("GET /logs?n=1 HTTP/1.1\n") == "/logs"


def test_ir_midea_frames_exist_but_daikin_not_imported_by_main() -> None:
    """Midea canned is used; Daikin must stay out of main.py."""
    import ir_midea
    from ir_midea import HeatpumpCommand, classic_frames, hex_frame

    frames = classic_frames(
        HeatpumpCommand(power=True, mode="FAN", fan="F5", temp_c=24)
    )
    assert len(frames) == 3
    assert all(len(f) == 6 for f in frames)
    assert "B2" in hex_frame(frames[0])
    main_src = (MP_DIR / "main.py").read_text(encoding="ascii")
    for line in main_src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "ir_daikin" not in stripped
        assert "from ir_daikin" not in stripped
        assert "import ir_daikin" not in stripped
