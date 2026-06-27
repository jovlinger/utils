"""Coolix / Midea24-style 48-bit AC protocol encoder.

Office captures match the public Midea 3-byte state protocol:
``B2, fan/state, temp/mode`` with each byte followed by its bitwise inverse.
The Office remote repeats the main frame, then emits a model-specific secondary
``D5`` frame for powered-on state commands.
"""

from __future__ import annotations

from typing import List, Sequence

from . import Fan, Mode, State

START_PULSE_US: int = 4_500
START_SPACE_US: int = 4_500
PULSE_US: int = 560
SPACE_ZERO_US: int = 560
SPACE_ONE_US: int = 1_680
GAP_US: int = 5_200

_FAN_NIBBLE: dict[Fan, int] = {
    Fan.F1: 0x9,
    Fan.F2: 0x9,
    Fan.F3: 0x5,
    Fan.F4: 0x3,
    Fan.F5: 0x3,
    Fan.AUTO: 0xB,
    Fan.SILENT: 0x9,
}

_MODE_NIBBLE: dict[Mode, int] = {
    Mode.AUTO: 0x8,
    Mode.COOL: 0x0,
    Mode.DRY: 0x4,
    Mode.HEAT: 0xC,
    Mode.FAN: 0x4,
}

# Midea's published temperature nibble order is not linear.
_TEMP_NIBBLE_BY_C: dict[int, int] = {
    17: 0x0,
    18: 0x1,
    19: 0x3,
    20: 0x2,
    21: 0x6,
    22: 0x7,
    23: 0x5,
    24: 0x4,
    25: 0xC,
    26: 0xD,
    27: 0x9,
    28: 0x8,
    29: 0xA,
    30: 0xB,
}


def _with_complements(data: Sequence[int]) -> List[int]:
    out: List[int] = []
    for byte in data:
        out.append(byte & 0xFF)
        out.append((~byte) & 0xFF)
    return out


def _office_secondary_frame(data: Sequence[int]) -> List[int]:
    fan_nibble = (data[1] >> 4) & 0x0F
    fan_code = {
        0x1: 0x65,
        0x3: 0x64,
        0x5: 0x3C,
        0x9: 0x28,
        0xB: 0x66,
    }.get(fan_nibble, 0x28)
    temp_flag = 0x20 if ((data[2] >> 4) & 0x0F) == 0x6 else 0x00
    frame = [0xD5, fan_code, temp_flag, 0x01, 0x00]
    frame.append(sum(frame) & 0xFF)
    return frame


def _bytes_to_mode2(frame: Sequence[int]) -> List[str]:
    lines: List[str] = ["pulse %d" % START_PULSE_US, "space %d" % START_SPACE_US]
    for byte in frame:
        for bit_index in range(7, -1, -1):
            bit = (byte >> bit_index) & 1
            lines.append("pulse %d" % PULSE_US)
            lines.append("space %d" % (SPACE_ONE_US if bit else SPACE_ZERO_US))
    lines.append("pulse %d" % PULSE_US)
    return lines


def _state_data_bytes(state: State) -> List[int]:
    fan_nibble = _FAN_NIBBLE.get(state.fan, _FAN_NIBBLE[Fan.AUTO])
    state_nibble = 0xF if state.power else 0xB
    mode_nibble = _MODE_NIBBLE.get(state.mode, _MODE_NIBBLE[Mode.AUTO])
    temp_c = max(17, min(30, round(state.temp_c)))
    temp_nibble = _TEMP_NIBBLE_BY_C[temp_c]

    if not state.power:
        fan_nibble = 0x7
        temp_nibble = 0xE
    return [
        0xB2,
        (fan_nibble << 4) | state_nibble,
        (temp_nibble << 4) | mode_nibble,
    ]


def dumps(state: State) -> str:
    """Encode ``state`` as Midea mode2 text suitable for ``ir-ctl --send``."""
    data = _state_data_bytes(state)
    frame = _with_complements(data)
    lines = _bytes_to_mode2(frame)
    lines.append("space %d" % GAP_US)
    lines.extend(_bytes_to_mode2(frame))
    lines.append("space %d" % GAP_US)
    if state.power:
        lines.extend(_bytes_to_mode2(_office_secondary_frame(data)))
        lines.append("space %d" % GAP_US)
    return "\n".join(lines) + "\n"
