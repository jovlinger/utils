"""Onboard deployment configuration from environment variables."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet, Mapping, Optional

from common.heatpumpirctl.profiles import (
    DEFAULT_IR_PROTOCOL,
    GENERIC_SEND_BEHAVIOR,
    HAIER_YRW02,
    LEGACY_DAIKIN_SEND_BEHAVIOR,
    MIDEA_CLASSIC,
    SEND_BEHAVIOR_PROTOCOL_ALIASES,
    normalize_protocol_name,
    protocol_from_env,
)


DEFAULT_ZONE_NAME = "default"
DEFAULT_HARDWARE_PROFILE = "pi_zero_2w_htu21d_ir"
DEFAULT_SEND_BEHAVIOR = GENERIC_SEND_BEHAVIOR
DEFAULT_REPORT_BEHAVIOR = "sensor_readings"
DEFAULT_SENSOR_DRIVER = "htu21d"
DEFAULT_IR_TRANSPORT = "lirc"
DEFAULT_IR_DEVICE = "/dev/lirc0"
PICO2W_HARDWARE_PROFILE = "pico2w_aht20_ir"
PICO2W_SENSOR_DRIVER = "aht20"
PICO2W_IR_TRANSPORT = "pico_gpio"
PICO2W_IR_DEVICE = "gp14"


@dataclass(frozen=True)
class HardwareProfile:
    """Physical device capability bundle."""

    name: str
    sensor_driver: str
    ir_transport: str
    ir_device: str
    send_behaviors: FrozenSet[str]
    ir_protocols: FrozenSet[str]
    report_behaviors: FrozenSet[str]


@dataclass(frozen=True)
class OnboardDeploymentConfig:
    """One deployed onboard unit and the behaviors enabled on it."""

    zone_name: str
    hardware_profile: str
    send_behavior: str
    report_behavior: str
    sensor_driver: str
    ir_transport: str
    ir_device: str
    ir_protocol: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "zone_name": self.zone_name,
            "hardware_profile": self.hardware_profile,
            "send_behavior": self.send_behavior,
            "report_behavior": self.report_behavior,
            "sensor_driver": self.sensor_driver,
            "ir_transport": self.ir_transport,
            "ir_device": self.ir_device,
            "ir_protocol": self.ir_protocol,
        }


SUPPORTED_SEND_BEHAVIORS: FrozenSet[str] = frozenset(
    {GENERIC_SEND_BEHAVIOR, LEGACY_DAIKIN_SEND_BEHAVIOR}
    | set(SEND_BEHAVIOR_PROTOCOL_ALIASES)
)
SUPPORTED_HEATPUMP_PROTOCOLS: FrozenSet[str] = frozenset(
    {DEFAULT_IR_PROTOCOL, MIDEA_CLASSIC, HAIER_YRW02}
)


SUPPORTED_HARDWARE_PROFILES: Mapping[str, HardwareProfile] = {
    DEFAULT_HARDWARE_PROFILE: HardwareProfile(
        name=DEFAULT_HARDWARE_PROFILE,
        sensor_driver=DEFAULT_SENSOR_DRIVER,
        ir_transport=DEFAULT_IR_TRANSPORT,
        ir_device=DEFAULT_IR_DEVICE,
        send_behaviors=SUPPORTED_SEND_BEHAVIORS,
        ir_protocols=SUPPORTED_HEATPUMP_PROTOCOLS,
        report_behaviors=frozenset({DEFAULT_REPORT_BEHAVIOR}),
    ),
    PICO2W_HARDWARE_PROFILE: HardwareProfile(
        name=PICO2W_HARDWARE_PROFILE,
        sensor_driver=PICO2W_SENSOR_DRIVER,
        ir_transport=PICO2W_IR_TRANSPORT,
        ir_device=PICO2W_IR_DEVICE,
        send_behaviors=SUPPORTED_SEND_BEHAVIORS,
        ir_protocols=SUPPORTED_HEATPUMP_PROTOCOLS,
        report_behaviors=frozenset({DEFAULT_REPORT_BEHAVIOR}),
    ),
}


def _env_value(
    environ: Mapping[str, str],
    name: str,
    default: str,
) -> str:
    raw = environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip()


def _validate_zone_name(zone_name: str) -> None:
    if "/" in zone_name:
        raise ValueError("ZONE_NAME must be a single URL path segment")
    if any(ch.isspace() for ch in zone_name):
        raise ValueError("ZONE_NAME must not contain whitespace")


def config_from_environ(
    environ: Optional[Mapping[str, str]] = None,
) -> OnboardDeploymentConfig:
    """Build and validate onboard deployment config from environment variables."""
    if environ is None:
        import os

        environ = os.environ

    zone_name = _env_value(environ, "ZONE_NAME", DEFAULT_ZONE_NAME)
    _validate_zone_name(zone_name)

    hardware_profile = _env_value(
        environ,
        "ONBOARD_HARDWARE_PROFILE",
        DEFAULT_HARDWARE_PROFILE,
    )
    profile = SUPPORTED_HARDWARE_PROFILES.get(hardware_profile)
    if profile is None:
        supported = ", ".join(sorted(SUPPORTED_HARDWARE_PROFILES))
        raise ValueError(
            f"unsupported ONBOARD_HARDWARE_PROFILE={hardware_profile!r}; "
            f"supported: {supported}"
        )

    send_behavior = _env_value(
        environ,
        "ONBOARD_SEND_BEHAVIOR",
        DEFAULT_SEND_BEHAVIOR,
    )
    if send_behavior not in profile.send_behaviors:
        supported = ", ".join(sorted(profile.send_behaviors))
        raise ValueError(
            f"unsupported ONBOARD_SEND_BEHAVIOR={send_behavior!r} "
            f"for {hardware_profile}; supported: {supported}"
        )
    ir_protocol = normalize_protocol_name(
        _env_value(
            environ,
            "ONBOARD_IR_PROTOCOL",
            protocol_from_env(environ, send_behavior),
        )
    )
    if ir_protocol not in profile.ir_protocols:
        supported = ", ".join(sorted(profile.ir_protocols))
        raise ValueError(
            f"unsupported ONBOARD_IR_PROTOCOL={ir_protocol!r} "
            f"for {hardware_profile}; supported: {supported}"
        )

    report_behavior = _env_value(
        environ,
        "ONBOARD_REPORT_BEHAVIOR",
        DEFAULT_REPORT_BEHAVIOR,
    )
    if report_behavior not in profile.report_behaviors:
        supported = ", ".join(sorted(profile.report_behaviors))
        raise ValueError(
            f"unsupported ONBOARD_REPORT_BEHAVIOR={report_behavior!r} "
            f"for {hardware_profile}; supported: {supported}"
        )

    sensor_driver = _env_value(environ, "SENSOR_DRIVER", profile.sensor_driver)
    if sensor_driver != profile.sensor_driver:
        raise ValueError(
            f"SENSOR_DRIVER={sensor_driver!r} does not match {hardware_profile} "
            f"({profile.sensor_driver!r})"
        )

    ir_transport = _env_value(environ, "IR_TRANSPORT", profile.ir_transport)
    if ir_transport != profile.ir_transport:
        raise ValueError(
            f"IR_TRANSPORT={ir_transport!r} does not match {hardware_profile} "
            f"({profile.ir_transport!r})"
        )

    ir_device = _env_value(environ, "IR_DEVICE", profile.ir_device)
    return OnboardDeploymentConfig(
        zone_name=zone_name,
        hardware_profile=hardware_profile,
        send_behavior=send_behavior,
        report_behavior=report_behavior,
        sensor_driver=sensor_driver,
        ir_transport=ir_transport,
        ir_device=ir_device,
        ir_protocol=ir_protocol,
    )
