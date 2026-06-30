"""Protocol registry for heat-pump IR dialects.

The transport is deliberately separate from the dialect. A Pi Zero may send
over LIRC and a Pico2W may send from GPIO, but both should select the same
protocol names for the same air-conditioner language.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType
from typing import Mapping, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from . import State


GENERIC_SEND_BEHAVIOR = "ir_heatpump"
LEGACY_DAIKIN_SEND_BEHAVIOR = "ir_daikin"

DAIKIN_ARC452A9 = "daikin_arc452a9"
MIDEA_CLASSIC = "midea_classic"
MIDEA24_COOLIX = "midea24_coolix"
HAIER_YRW02 = "haier_yrw02"
DEFAULT_IR_PROTOCOL = DAIKIN_ARC452A9


class HeatpumpProtocolModule(Protocol):
    """Minimal encoder interface implemented by protocol modules."""

    def dumps(self, state: "State") -> str:
        """Encode a state snapshot as ir-ctl mode2 text."""
        ...


@dataclass(frozen=True)
class HeatpumpIrProtocol:
    """A named IR dialect available to onboard senders."""

    name: str
    display_name: str
    module_name: str
    source: str


SUPPORTED_IR_PROTOCOLS: Mapping[str, HeatpumpIrProtocol] = {
    DAIKIN_ARC452A9: HeatpumpIrProtocol(
        name=DAIKIN_ARC452A9,
        display_name="Daikin/ARC452A9",
        module_name="ARC452A9",
        source="local derived dialect",
    ),
    MIDEA_CLASSIC: HeatpumpIrProtocol(
        name=MIDEA_CLASSIC,
        display_name="Midea classic 48-bit",
        module_name="MideaClassic",
        source="published Midea AC protocol plus office captures",
    ),
    MIDEA24_COOLIX: HeatpumpIrProtocol(
        name=MIDEA24_COOLIX,
        display_name="Midea24/Coolix 48-bit",
        module_name="MideaClassic",
        source="Coolix/Midea24 byte-complement protocol plus office captures",
    ),
    HAIER_YRW02: HeatpumpIrProtocol(
        name=HAIER_YRW02,
        display_name="Haier/YR-W02",
        module_name="HaierYRW02",
        source="published Haier YR-W02 protocol plus bedroom captures",
    ),
}

SEND_BEHAVIOR_PROTOCOL_ALIASES: Mapping[str, str] = {
    LEGACY_DAIKIN_SEND_BEHAVIOR: DAIKIN_ARC452A9,
    "ir_midea": MIDEA_CLASSIC,
    "ir_haier": HAIER_YRW02,
}


def normalize_protocol_name(value: Optional[str]) -> str:
    """Return a supported protocol name, accepting small spelling variations."""
    raw = (value or DEFAULT_IR_PROTOCOL).strip().lower().replace("-", "_")
    aliases = {
        "daikin": DAIKIN_ARC452A9,
        "arc452a9": DAIKIN_ARC452A9,
        "midea": MIDEA_CLASSIC,
        "midea_48": MIDEA_CLASSIC,
        "midea24": MIDEA24_COOLIX,
        "coolix": MIDEA24_COOLIX,
        "haier": HAIER_YRW02,
        "haier_yr_w02": HAIER_YRW02,
        "yrw02": HAIER_YRW02,
    }
    name = aliases.get(raw, raw)
    if name not in SUPPORTED_IR_PROTOCOLS:
        supported = ", ".join(sorted(SUPPORTED_IR_PROTOCOLS))
        raise ValueError(
            f"unsupported ONBOARD_IR_PROTOCOL={value!r}; supported: {supported}"
        )
    return name


def protocol_from_env(
    environ: Mapping[str, str],
    send_behavior: str,
) -> str:
    """Resolve the selected IR protocol from env, preserving old behavior names."""
    explicit = environ.get("ONBOARD_IR_PROTOCOL")
    if explicit is not None and explicit.strip():
        return normalize_protocol_name(explicit)
    alias = SEND_BEHAVIOR_PROTOCOL_ALIASES.get(send_behavior)
    if alias is not None:
        return alias
    return DEFAULT_IR_PROTOCOL


def protocol_spec(protocol_name: str) -> HeatpumpIrProtocol:
    """Return metadata for a supported protocol."""
    return SUPPORTED_IR_PROTOCOLS[normalize_protocol_name(protocol_name)]


def load_protocol_module(protocol_name: str) -> ModuleType:
    """Import and return the encoder module for a supported protocol."""
    spec = protocol_spec(protocol_name)
    return import_module(f"common.heatpumpirctl.{spec.module_name}")


def dumps(state: "State", protocol_name: str) -> str:
    """Encode ``state`` using the named protocol."""
    module = load_protocol_module(protocol_name)
    return module.dumps(state)
