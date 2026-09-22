"""Pure builders for onboard debug HTTP JSON (host-testable).

No socket / machine imports -- main.py wires transport around these.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from config import (
    BACKEND,
    DEBUG_PULLDOWN_GPIO,
    DEBUG_PULLUP_GPIO,
    HARDWARE_PROFILE,
    HTTP_PORT,
    IR_PROTOCOL,
    IR_RX_GPIO,
    IR_TRANSPORT,
    IR_TX_GPIO,
    LOG_CAPACITY,
    REPORT_BEHAVIOR,
    SEND_BEHAVIOR,
    SENSOR_DRIVER,
    STATUS_LED_DRIVER,
    ZONE_NAME,
)


def deployment_dict() -> Dict[str, Any]:
    return {
        "zone_name": ZONE_NAME,
        "hardware_profile": HARDWARE_PROFILE,
        "send_behavior": SEND_BEHAVIOR,
        "report_behavior": REPORT_BEHAVIOR,
        "sensor_driver": SENSOR_DRIVER,
        "ir_transport": IR_TRANSPORT,
        "ir_device": "gpio%d" % IR_TX_GPIO,
        "ir_protocol": IR_PROTOCOL,
        "backend": BACKEND,
        "status_led_driver": STATUS_LED_DRIVER,
    }


def network_dict(local_ip: str) -> Dict[str, Any]:
    return {
        "local_ip": local_ip,
        "onboard_url": "http://%s:%d" % (local_ip, HTTP_PORT),
    }


def build_healthz(
    *,
    uptime_s: int,
    epoch_s: int,
    local_ip: str,
    wifi_ready: bool,
    ntp_ok: bool,
    auth_ed25519_ready: bool,
    pullup_level: int,
    pulldown_level: int,
    log_lines: Sequence[str],
) -> Dict[str, Any]:
    lines: List[str] = list(log_lines)
    return {
        "ok": True,
        "service": "onboard-app",
        "hardware_backend": BACKEND,
        "runtime": "micropython",
        "deployment": deployment_dict(),
        "network": network_dict(local_ip),
        "esp32s3": {
            "uptime_seconds": uptime_s,
            "epoch_seconds": epoch_s,
            "wifi_ready": wifi_ready,
            "ntp_ok": ntp_ok,
            "auth_ed25519_ready": auth_ed25519_ready,
            "debug_pullup_gpio": DEBUG_PULLUP_GPIO,
            "debug_pulldown_gpio": DEBUG_PULLDOWN_GPIO,
            "debug_pullup_level": pullup_level,
            "debug_pulldown_level": pulldown_level,
            "ir_tx_gpio": IR_TX_GPIO,
            "ir_rx_gpio": IR_RX_GPIO,
        },
        "log_buffer": {
            "capacity": LOG_CAPACITY,
            "returned": len(lines),
            "lines": lines,
        },
    }


def build_logs(log_lines: Sequence[str]) -> Dict[str, Any]:
    return {"lines": list(log_lines), "path": None}


def build_gpio(pullup_level: int, pulldown_level: int) -> Dict[str, Any]:
    return {
        "pullup_gpio": DEBUG_PULLUP_GPIO,
        "pulldown_gpio": DEBUG_PULLDOWN_GPIO,
        "pullup_level": pullup_level,
        "pulldown_level": pulldown_level,
    }


def build_not_found(path: str) -> Dict[str, Any]:
    return {"ok": False, "error": "not_found", "path": path}


def parse_request_path(request_text: str) -> str:
    """Extract path from a raw HTTP request start-line (no query)."""
    first_nl: int = request_text.find("\n")
    line: str = request_text if first_nl < 0 else request_text[:first_nl]
    if line.endswith("\r"):
        line = line[:-1]
    parts: List[str] = line.split(" ")
    if len(parts) < 2:
        return "/"
    path: str = parts[1]
    q: int = path.find("?")
    return path if q < 0 else path[:q]


def route_get(
    path: str,
    *,
    healthz: Mapping[str, Any],
    logs: Mapping[str, Any],
    gpio: Mapping[str, Any],
    ir_on: Optional[Mapping[str, Any]] = None,
    ir_off: Optional[Mapping[str, Any]] = None,
) -> tuple[int, Dict[str, Any]]:
    """Route debug paths. IR handlers pass prebuilt bodies from main."""
    if path == "/healthz":
        return 200, dict(healthz)
    if path == "/logs":
        return 200, dict(logs)
    if path == "/gpio":
        return 200, dict(gpio)
    if path == "/ir/on" and ir_on is not None:
        return 200, dict(ir_on)
    if path == "/ir/off" and ir_off is not None:
        return 200, dict(ir_off)
    return 404, build_not_found(path)
