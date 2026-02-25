#!/usr/bin/env python3
"""Thin CLI around heatpumpirctl: build State from args, dump to ir-ctl mode2, send via ir-ctl.

Uses heatpumpirctl.State + ARC452A9.dump/dumps only. Device: /dev/lirc0.

Usage:
  ./daikin-send.py [--power on|off] [--mode auto|dry|cool|heat|fan] \
      [--temp 10-32] [--fan 1|2|3|4|5|auto|silent] [--swing] [--powerful] \
      [--econo] [--comfort] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "onboard"))
from heatpumpirctl import Fan, Mode, State
from heatpumpirctl import ARC452A9 as proto

LIRC_TX: str = "/dev/lirc0"

_MODE_BY_NAME = {m.name.lower(): m for m in Mode}
_FAN_BY_NAME = {
    "1": Fan.F1,
    "2": Fan.F2,
    "3": Fan.F3,
    "4": Fan.F4,
    "5": Fan.F5,
    "auto": Fan.AUTO,
    "silent": Fan.SILENT,
}


def _hex(data) -> str:
    return " ".join("%02x" % b for b in data)


def send_mode2(mode2_text: str) -> None:
    """Send mode2 text via ir-ctl."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(mode2_text)
        fname = f.name
    try:
        subprocess.run(["ir-ctl", "-d", LIRC_TX, "--send", fname], check=True)
    finally:
        os.unlink(fname)


def main() -> None:
    ap = argparse.ArgumentParser(description="Send Daikin IR command (ARC452A9).")
    ap.add_argument(
        "--power", choices=("on", "off"), default="on", help="Power (default: on)"
    )
    ap.add_argument(
        "--mode",
        choices=tuple(_MODE_BY_NAME),
        default="heat",
        help="Mode (default: heat)",
    )
    ap.add_argument(
        "--temp",
        type=int,
        default=22,
        metavar="C",
        help="Temperature 10-32 °C (default: 22)",
    )
    ap.add_argument(
        "--fan",
        choices=tuple(_FAN_BY_NAME),
        default="auto",
        help="Fan (default: auto)",
    )
    ap.add_argument("--swing", action="store_true", help="Enable swing")
    ap.add_argument("--powerful", action="store_true", help="Powerful mode (~20 min)")
    ap.add_argument("--econo", action="store_true", help="Econo mode")
    ap.add_argument("--comfort", action="store_true", help="Comfort mode (frame1)")
    ap.add_argument("--dry-run", action="store_true", help="Print only, do not send IR")
    args = ap.parse_args()

    state = (
        State()
        .set_power(args.power == "on")
        .set_mode(_MODE_BY_NAME[args.mode])
        .set_temp(args.temp)
        .set_fan(_FAN_BY_NAME[args.fan])
        .set_swing(args.swing)
        .set_powerful(args.powerful)
        .set_econo(args.econo)
        .set_comfort(args.comfort)
    )

    f1, f3 = proto.dump(state)
    mode2 = proto.dumps(state)

    print("Sending: %s" % state.summary())
    print("  F1: %s" % _hex(f1))
    print("  F3: %s" % _hex(f3))

    if args.dry_run:
        print("(dry-run: not sending)")
        return

    send_mode2(mode2)
    print("Sent.")


if __name__ == "__main__":
    main()
