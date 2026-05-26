from __future__ import annotations

from pathlib import Path

import pytest

from common.deployment_config import (
    DEFAULT_HARDWARE_PROFILE,
    DEFAULT_IR_DEVICE,
    DEFAULT_IR_TRANSPORT,
    DEFAULT_REPORT_BEHAVIOR,
    DEFAULT_SEND_BEHAVIOR,
    DEFAULT_SENSOR_DRIVER,
    DEFAULT_ZONE_NAME,
    config_from_environ,
)


def test_config_defaults_to_current_hardware_stack() -> None:
    cfg = config_from_environ({})
    assert cfg.zone_name == DEFAULT_ZONE_NAME
    assert cfg.hardware_profile == DEFAULT_HARDWARE_PROFILE
    assert cfg.send_behavior == DEFAULT_SEND_BEHAVIOR
    assert cfg.report_behavior == DEFAULT_REPORT_BEHAVIOR
    assert cfg.sensor_driver == DEFAULT_SENSOR_DRIVER
    assert cfg.ir_transport == DEFAULT_IR_TRANSPORT
    assert cfg.ir_device == DEFAULT_IR_DEVICE


def test_config_accepts_kitchen_deployment() -> None:
    cfg = config_from_environ(
        {
            "ZONE_NAME": "kitchen",
            "ONBOARD_HARDWARE_PROFILE": "pi_zero_2w_htu21d_ir",
            "ONBOARD_SEND_BEHAVIOR": "ir_daikin",
            "ONBOARD_REPORT_BEHAVIOR": "sensor_readings",
            "SENSOR_DRIVER": "htu21d",
            "IR_TRANSPORT": "lirc",
            "IR_DEVICE": "/dev/lirc0",
        }
    )
    assert cfg.to_public_dict() == {
        "zone_name": "kitchen",
        "hardware_profile": "pi_zero_2w_htu21d_ir",
        "send_behavior": "ir_daikin",
        "report_behavior": "sensor_readings",
        "sensor_driver": "htu21d",
        "ir_transport": "lirc",
        "ir_device": "/dev/lirc0",
    }


def test_config_rejects_unknown_behavior() -> None:
    with pytest.raises(ValueError, match="ONBOARD_SEND_BEHAVIOR"):
        config_from_environ({"ONBOARD_SEND_BEHAVIOR": "mqtt"})


def test_config_rejects_zone_name_that_is_not_path_segment() -> None:
    with pytest.raises(ValueError, match="ZONE_NAME"):
        config_from_environ({"ZONE_NAME": "kitchen/main"})

    with pytest.raises(ValueError, match="ZONE_NAME"):
        config_from_environ({"ZONE_NAME": "kitchen main"})


def test_kitchen_env_sample_matches_supported_config() -> None:
    sample_path = Path(__file__).resolve().parents[2] / "config" / "kitchen.env.sample"
    values: dict[str, str] = {}
    for raw in sample_path.read_text(encoding="ascii").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        assert sep == "=", line
        values[key] = value

    cfg = config_from_environ(values)
    assert cfg.zone_name == "kitchen"
    assert cfg.hardware_profile == "pi_zero_2w_htu21d_ir"
