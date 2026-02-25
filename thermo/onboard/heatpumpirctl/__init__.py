"""Heat-pump IR control — shared state model for Daikin remotes.

State is the mutable dataclass holding the full remote/unit state.
Protocol modules (e.g. ARC452A9) provide loads/dumps to convert between
State and ir-ctl byte sequences.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Mode(Enum):
    AUTO = 0
    DRY = 2
    COOL = 3
    HEAT = 4
    FAN = 6


class Fan(Enum):
    F1 = 3
    F2 = 4
    F3 = 5
    F4 = 6
    F5 = 7
    AUTO = 0xA
    SILENT = 0xB


_FAN_LABELS = {
    Fan.F1: "1/5",
    Fan.F2: "2/5",
    Fan.F3: "3/5",
    Fan.F4: "4/5",
    Fan.F5: "5/5",
    Fan.AUTO: "Auto",
    Fan.SILENT: "Silent",
}


@dataclass
class State:
    """Mutable snapshot of the heat-pump remote / head-unit state.

    All setters return *self* so calls can be chained::

        s = State().set_power(True).set_mode(Mode.HEAT).set_temp(22)
    """

    power: bool = False
    mode: Mode = Mode.AUTO
    temp_c: int = 25
    fan: Fan = Fan.AUTO
    swing: bool = False
    powerful: bool = False
    econo: bool = False
    comfort: bool = False

    timer_on_minutes: Optional[int] = None
    timer_off_minutes: Optional[int] = None

    # Raw frame bytes that produced this state (set by loads).
    raw_f1: Optional[List[int]] = field(default=None, repr=False)
    raw_f3: Optional[List[int]] = field(default=None, repr=False)
    # Original ir-ctl text that was parsed (set by loads).
    raw_ir: Optional[str] = field(default=None, repr=False)

    truncated: bool = field(default=False, repr=False)

    # -- chaining setters --

    def set_power(self, on: bool) -> State:
        self.power = on
        return self

    def set_mode(self, mode: Mode) -> State:
        self.mode = mode
        return self

    def set_temp(self, temp_c: int) -> State:
        self.temp_c = max(10, min(32, temp_c))
        return self

    def set_fan(self, fan: Fan) -> State:
        self.fan = fan
        return self

    def set_swing(self, on: bool) -> State:
        self.swing = on
        return self

    def set_powerful(self, on: bool) -> State:
        self.powerful = on
        return self

    def set_econo(self, on: bool) -> State:
        self.econo = on
        return self

    def set_comfort(self, on: bool) -> State:
        self.comfort = on
        return self

    def set_timer_on(self, minutes: Optional[int]) -> State:
        self.timer_on_minutes = minutes
        return self

    def set_timer_off(self, minutes: Optional[int]) -> State:
        self.timer_off_minutes = minutes
        return self

    def summary(self) -> str:
        parts = [
            "power=%s" % ("ON" if self.power else "OFF"),
            "mode=%s" % self.mode.name,
            "temp=%dC" % self.temp_c,
            "fan=%s" % _FAN_LABELS.get(self.fan, self.fan.name),
            "swing=%s" % ("on" if self.swing else "off"),
        ]
        if self.powerful:
            parts.append("powerful")
        if self.econo:
            parts.append("econo")
        if self.comfort:
            parts.append("comfort")
        if self.timer_on_minutes is not None:
            parts.append("timer_on=%dm" % self.timer_on_minutes)
        if self.timer_off_minutes is not None:
            parts.append("timer_off=%dm" % self.timer_off_minutes)
        if self.truncated:
            parts.append("(truncated)")
        return " ".join(parts)
