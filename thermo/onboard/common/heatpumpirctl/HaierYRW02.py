"""Haier YR-W02 112-bit AC protocol encoder.

Bedroom captures decode as Haier YR-W02 native bytes. The checksum is the low
byte of the sum of bytes 0..12. The final "button" byte is not usually needed
for absolute state application, but setting it close to the initiating action
matches captured remotes better.
"""

from __future__ import annotations

from typing import List, Sequence

from . import Fan, Mode, State

HEADER1_PULSE_US: int = 3_075
HEADER1_SPACE_US: int = 3_045
HEADER2_PULSE_US: int = 3_085
HEADER2_SPACE_US: int = 4_415
PULSE_US: int = 570
SPACE_ZERO_US: int = 530
SPACE_ONE_US: int = 1_640

_FAN_BYTE: dict[Fan, int] = {
    Fan.F1: 0x60,
    Fan.F2: 0x40,
    Fan.F3: 0x40,
    Fan.F4: 0x20,
    Fan.F5: 0x20,
    Fan.AUTO: 0xA0,
    Fan.SILENT: 0x60,
}

_MODE_BYTE: dict[Mode, int] = {
    Mode.AUTO: 0x00,
    Mode.COOL: 0x20,
    Mode.DRY: 0x40,
    Mode.HEAT: 0x80,
    Mode.FAN: 0xC0,
}

_BUTTON_POWER: int = 0x05
_BUTTON_MODE: int = 0x06
_BUTTON_QUIET: int = 0x08
_BUTTON_TEMP_UP: int = 0x00
_BUTTON_TEMP_DOWN: int = 0x01


def _checksum(bytes_without_sum: Sequence[int]) -> int:
    return sum(bytes_without_sum) & 0xFF


def _button_for_state(state: State) -> int:
    if state.fan == Fan.SILENT or state.comfort:
        return _BUTTON_QUIET
    if not state.power:
        return _BUTTON_POWER
    if state.mode != Mode.AUTO:
        return _BUTTON_MODE
    return _BUTTON_TEMP_UP


def _state_bytes(state: State) -> List[int]:
    temp_c = max(16, min(30, round(state.temp_c)))
    swing_v = 0x2
    power = 0x40 if state.power else 0x00
    fan = _FAN_BYTE.get(state.fan, _FAN_BYTE[Fan.AUTO])
    quiet = 0x80 if state.fan == Fan.SILENT or state.comfort else 0x00
    mode = _MODE_BYTE.get(state.mode, _MODE_BYTE[Mode.AUTO])

    body = [
        0xA6,
        ((temp_c - 16) << 4) | swing_v,
        0x00,
        0x00,
        power,
        fan,
        quiet,
        mode,
        0x00,
        0x00,
        0x20,
        0x00,
        _button_for_state(state),
    ]
    body.append(_checksum(body))
    return body


def _bytes_to_mode2(frame: Sequence[int]) -> List[str]:
    lines: List[str] = [
        "pulse %d" % HEADER1_PULSE_US,
        "space %d" % HEADER1_SPACE_US,
        "pulse %d" % HEADER2_PULSE_US,
        "space %d" % HEADER2_SPACE_US,
    ]
    for byte in frame:
        for bit_index in range(7, -1, -1):
            bit = (byte >> bit_index) & 1
            lines.append("pulse %d" % PULSE_US)
            lines.append("space %d" % (SPACE_ONE_US if bit else SPACE_ZERO_US))
    lines.append("pulse %d" % PULSE_US)
    return lines


def dumps(state: State) -> str:
    """Encode ``state`` as Haier YR-W02 mode2 text for ``ir-ctl --send``."""
    return "\n".join(_bytes_to_mode2(_state_bytes(state))) + "\n"
