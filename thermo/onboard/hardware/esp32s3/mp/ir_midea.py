"""Midea24 / Coolix IR frame builder (port of ir.toit / pico2w ir.rs).

Kept in-tree for later RMT TX. Not uploaded to the board by default
(see install/upload.manifest). Pure framing -- no RMT / gpio imports.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple


MIDEA_START_PULSE_US: int = 4500
MIDEA_START_SPACE_US: int = 4500
MIDEA_PULSE_US: int = 560
MIDEA_SPACE_ZERO_US: int = 560
MIDEA_SPACE_ONE_US: int = 1680
MIDEA_GAP_US: int = 5200
CARRIER_HZ: int = 38_000


class HeatpumpCommand:
    def __init__(
        self,
        power: bool,
        mode: str,
        fan: str,
        temp_c: int = 24,
    ) -> None:
        self.power: bool = power
        self.mode: str = mode  # AUTO COOL DRY HEAT FAN
        self.fan: str = fan  # F1..F5 AUTO SILENT
        self.temp_c: int = temp_c


def temp_nibble(temp_c: int) -> int:
    t: int = temp_c
    if t < 17:
        t = 17
    if t > 30:
        t = 30
    table: dict[int, int] = {
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
    return table[t]


def fan_nibble(fan: str) -> int:
    if fan == "F3":
        return 0x5
    if fan in ("F4", "F5"):
        return 0x3
    if fan == "AUTO":
        return 0xB
    return 0x9  # F1 F2 SILENT


def mode_nibble(mode: str) -> int:
    if mode == "AUTO":
        return 0x8
    if mode == "COOL":
        return 0x0
    if mode == "HEAT":
        return 0xC
    return 0x4  # DRY or FAN


def state_bytes(command: HeatpumpCommand) -> bytes:
    fan_n: int = fan_nibble(command.fan)
    state_n: int = 0xF if command.power else 0xB
    mode_n: int = mode_nibble(command.mode)
    temp_n: int = temp_nibble(command.temp_c)
    if not command.power:
        fan_n = 0x7
        temp_n = 0xE
    return bytes(
        [
            0xB2,
            (fan_n << 4) | state_n,
            (temp_n << 4) | mode_n,
        ]
    )


def complement_frame(data: bytes) -> bytes:
    return bytes(
        [
            data[0],
            data[0] ^ 0xFF,
            data[1],
            data[1] ^ 0xFF,
            data[2],
            data[2] ^ 0xFF,
        ]
    )


def secondary_frame(data: bytes) -> bytes:
    fan_hi: int = data[1] >> 4
    fan_code: int = 0x28
    if fan_hi == 0x1:
        fan_code = 0x65
    elif fan_hi == 0x3:
        fan_code = 0x64
    elif fan_hi == 0x5:
        fan_code = 0x3C
    elif fan_hi == 0x9:
        fan_code = 0x28
    elif fan_hi == 0xB:
        fan_code = 0x66
    temp_flag: int = 0x20 if (data[2] >> 4) == 0x6 else 0x00
    frame: bytearray = bytearray([0xD5, fan_code, temp_flag, 0x01, 0x00, 0x00])
    frame[5] = (frame[0] + frame[1] + frame[2] + frame[3] + frame[4]) & 0xFF
    return bytes(frame)


def classic_frames(command: HeatpumpCommand) -> List[bytes]:
    data: bytes = state_bytes(command)
    state: bytes = complement_frame(data)
    if command.power:
        return [state, state, secondary_frame(data)]
    return [state, state]


def hex_frame(frame: bytes) -> str:
    return " ".join("%02X" % b for b in frame)


def mark_space_timings(frames: Sequence[bytes]) -> List[Tuple[int, int]]:
    """Return (mark_us, space_us) pairs for RMT TX (carrier on during mark)."""
    out: List[Tuple[int, int]] = []
    for frame in frames:
        out.append((MIDEA_START_PULSE_US, MIDEA_START_SPACE_US))
        for byte in frame:
            for bit in range(7, -1, -1):
                space: int = (
                    MIDEA_SPACE_ONE_US
                    if ((byte >> bit) & 1) == 1
                    else MIDEA_SPACE_ZERO_US
                )
                out.append((MIDEA_PULSE_US, space))
        out.append((MIDEA_PULSE_US, MIDEA_GAP_US))
    return out
