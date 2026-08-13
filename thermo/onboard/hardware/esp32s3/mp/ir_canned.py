"""Canned office Midea IR on/off sequences for bootstrap TX.

Goldens match pico2w/src/ir.rs office cool on/off frame tests.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from ir_midea import HeatpumpCommand, classic_frames, hex_frame, mark_space_timings

# Office cool @ 20C fan F4 -- pico encodes_office_cool_on_midea_frame
CANNED_ON = HeatpumpCommand(power=True, mode="COOL", fan="F4", temp_c=20)
# Same mode/fan/temp with power off -- encodes_office_cool_off / power_off sequence
CANNED_OFF = HeatpumpCommand(power=False, mode="COOL", fan="F4", temp_c=20)

# Compact hex without spaces (TSL / pico style).
ON_STATE_HEX: str = "B24D3FC020DF"
OFF_STATE_HEX: str = "B24D7B84E01F"


def frames_for(power_on: bool) -> List[bytes]:
    cmd: HeatpumpCommand = CANNED_ON if power_on else CANNED_OFF
    return classic_frames(cmd)


def frames_hex(power_on: bool) -> List[str]:
    return [hex_frame(f).replace(" ", "") for f in frames_for(power_on)]


def timings_us(power_on: bool) -> List[Tuple[int, int]]:
    return mark_space_timings(frames_for(power_on))


def canned_result(power_on: bool) -> Dict[str, object]:
    action: str = "ir_canned_on" if power_on else "ir_canned_off"
    hexes: List[str] = frames_hex(power_on)
    marks: Sequence[Tuple[int, int]] = timings_us(power_on)
    return {
        "ok": True,
        "action": action,
        "protocol": "midea24_coolix",
        "command": {
            "power": power_on,
            "mode": "COOL",
            "fan": "F4",
            "temp_c": 20,
        },
        "frames_hex": hexes,
        "mark_space_pairs": len(marks),
    }
