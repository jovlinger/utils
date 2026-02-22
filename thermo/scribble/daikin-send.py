#!/usr/bin/env python3
"""Build and send Daikin IR frames from CLI options (Pi Zero 2W + ANAVI IR pHAT).

Sends via ir-ctl to /dev/lirc0. Protocol from blafois/Daikin-IR-Reverse:
3 frames (8, 8, 19 bytes), pulse-distance encoding, 38kHz carrier.

Usage:
  python3 daikin-send.py [--power on|off] [--mode auto|dry|cool|heat|fan] [--temp 10-30] [--fan 1|2|3|4|5|auto|silent] [--swing] [--powerful] [--econo] [--comfort]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from typing import Dict, List, Sequence

# LIRC TX device on Pi Zero 2W with ANAVI IR pHAT (GPIO 18).
LIRC_TX: str = "/dev/lirc0"

# Pulse-distance timing (microseconds). Blafois: HIGH ~452, 0 ~419, 1 ~1286.
PULSE_US: int = 430
SPACE_ZERO_US: int = 420
SPACE_ONE_US: int = 1320
START_PULSE_US: int = 3400
START_SPACE_US: int = 1750
GAP_BETWEEN_FRAMES_US: int = 30_000

MODE_MAP: Dict[str, int] = {
    "auto": 0x0,
    "dry": 0x2,
    "cool": 0x3,
    "heat": 0x4,
    "fan": 0x6,
}
FAN_MAP: Dict[str, int] = {
    "1": 0x3,
    "2": 0x4,
    "3": 0x5,
    "4": 0x6,
    "5": 0x7,
    "auto": 0xA,
    "silent": 0xB,
}


def checksum(data: Sequence[int]) -> int:
    return sum(data) & 0xFF


def byte_to_bits_lsb(b: int) -> List[int]:
    return [(b >> i) & 1 for i in range(8)]


def frame_to_pulse_train(frame_bytes: Sequence[int]) -> List[int]:
    """Encode one frame as pulse/space list (start + bits, LSB first)."""
    out = [START_PULSE_US, START_SPACE_US]
    for b in frame_bytes:
        for bit in byte_to_bits_lsb(b):
            out.append(PULSE_US)
            out.append(SPACE_ONE_US if bit else SPACE_ZERO_US)
    return out


def build_frame1(comfort: bool = False) -> List[int]:
    # 11 da 27 00 c5 00 [00|10] checksum
    body = [0x11, 0xDA, 0x27, 0x00, 0xC5, 0x00, 0x10 if comfort else 0x00]
    body.append(checksum(body))
    return body


def build_frame2() -> List[int]:
    return [0x11, 0xDA, 0x27, 0x00, 0x42, 0x00, 0x00, 0x54]


def build_frame3(
    power_on: bool,
    mode: str,
    temp_c: int,
    fan_nib: str,
    swing: bool,
    powerful: bool,
    econo: bool,
) -> List[int]:
    # Header 11 da 27 00 00, then byte5 = mode (high nibble) + power/timer (low nibble)
    # Byte 5: bit0=1 always, bit1=timer off, bit2=timer on, bit3=power (1=on). So 0x08|0x01 = on.
    byte5 = (
        (MODE_MAP.get(mode, 0x4) << 4) | 0x09
        if power_on
        else (MODE_MAP.get(mode, 0x4) << 4) | 0x08
    )
    temp_byte = max(10, min(30, temp_c)) * 2
    # Byte 8: fan (high nibble), swing 0 or 0xF (low nibble)
    fan_byte = (FAN_MAP.get(fan_nib, 0xA) << 4) | (0xF if swing else 0x0)
    body = [
        0x11,
        0xDA,
        0x27,
        0x00,
        0x00,
        byte5,
        temp_byte,
        0x00,
        fan_byte,
        0x00,
        0x00,
        0x06,
        0x60,
        0x01 if powerful else 0x00,
        0x00,
        0xC1,
        0x80,
        0x04 if econo else 0x00,
    ]
    body.append(checksum(body))
    return body


def build_full_train(
    frame1: Sequence[int], frame2: Sequence[int], frame3: Sequence[int]
) -> List[int]:
    """Pulse train for all 3 frames with inter-frame gaps."""
    train = []
    for i, frame in enumerate([frame1, frame2, frame3]):
        train.extend(frame_to_pulse_train(frame))
        if i < 2:
            train.append(GAP_BETWEEN_FRAMES_US)
    return train


def send_pulse_train(pulses_us: Sequence[int]) -> None:
    """Send pulse/space list via ir-ctl. Expects [pulse, space, pulse, space, ...]."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for i, val in enumerate(pulses_us):
            kind = "pulse" if i % 2 == 0 else "space"
            f.write(f"{kind} {val}\n")
        fname = f.name
    subprocess.run(["ir-ctl", "-d", LIRC_TX, "--send", fname], check=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Send Daikin IR command (Pi Zero 2W).")
    ap.add_argument(
        "--power", choices=("on", "off"), default="on", help="Power (default: on)"
    )
    ap.add_argument(
        "--mode",
        choices=("auto", "dry", "cool", "heat", "fan"),
        default="heat",
        help="Mode (default: heat)",
    )
    ap.add_argument(
        "--temp",
        type=int,
        default=22,
        metavar="C",
        help="Temperature 10-30 °C (default: 22)",
    )
    ap.add_argument(
        "--fan",
        choices=("1", "2", "3", "4", "5", "auto", "silent"),
        default="auto",
        help="Fan (default: auto)",
    )
    ap.add_argument("--swing", action="store_true", help="Enable swing")
    ap.add_argument("--powerful", action="store_true", help="Powerful mode (~20 min)")
    ap.add_argument("--econo", action="store_true", help="Econo mode")
    ap.add_argument("--comfort", action="store_true", help="Comfort mode (frame1)")
    ap.add_argument("--dry-run", action="store_true", help="Print only, do not send IR")
    args = ap.parse_args()

    temp_c = max(10, min(30, args.temp))
    f1 = build_frame1(comfort=args.comfort)
    f2 = build_frame2()
    f3 = build_frame3(
        power_on=(args.power == "on"),
        mode=args.mode,
        temp_c=temp_c,
        fan_nib=args.fan,
        swing=args.swing,
        powerful=args.powerful,
        econo=args.econo,
    )

    print("Sending (human-readable):")
    print(
        f"  power={args.power}  mode={args.mode}  temp={temp_c}°C  fan={args.fan}  swing={args.swing}  powerful={args.powerful}  econo={args.econo}  comfort={args.comfort}"
    )
    print("  F1:", " ".join(f"{b:02x}" for b in f1))
    print("  F2:", " ".join(f"{b:02x}" for b in f2))
    print("  F3:", " ".join(f"{b:02x}" for b in f3))

    if args.dry_run:
        print("(dry-run: not sending)")
        return

    train = build_full_train(f1, f2, f3)
    send_pulse_train(train)
    print("Sent.")


if __name__ == "__main__":
    main()
