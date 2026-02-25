#!/usr/bin/env python3
"""Minimal interactive Daikin IR control for Pi Zero 2. State + one-letter menu; Enter sends via ir-ctl.

Keys: 0-5 fan | h/c/f/d/a mode | Space power | ↑↓ temp | Enter send.
After send, decodes and warns if decode != sent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import termios
import tty

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "onboard"))
from heatpumpirctl import Fan, Mode, State
from heatpumpirctl import ARC452A9 as proto

LIRC_TX = "/dev/lirc0"

FAN_KEY = {"0": Fan.AUTO, "1": Fan.F1, "2": Fan.F2, "3": Fan.F3, "4": Fan.F4, "5": Fan.F5}
MODE_KEY = {"h": Mode.HEAT, "c": Mode.COOL, "f": Mode.FAN, "d": Mode.DRY, "a": Mode.AUTO}


def getkey() -> str:
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        c = sys.stdin.read(1)
        if c == "\x1b":
            c2 = sys.stdin.read(2)
            if c2 == "[A":
                return "UP"
            if c2 == "[B":
                return "DOWN"
        return c
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def send_state(state: State) -> bool:
    """Send state via ir-ctl. Return True if decode == sent."""
    mode2 = proto.dumps(state)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(mode2)
        path = f.name
    try:
        subprocess.run(["ir-ctl", "-d", LIRC_TX, "--send", path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error sending state: {e}")
        return False
    finally:
        os.unlink(path)
    return proto.round_trip_ok(state)


def main() -> None:
    state = State().set_power(False).set_mode(Mode.HEAT).set_temp(22).set_fan(Fan.AUTO)
    menu = "0-5 fan | h/c/f/d/a mode | Space power | ↑↓ temp | Enter send | q quit"

    first = True
    while True:
        p = "ON" if state.power else "OFF"
        m = state.mode.name
        t = state.temp_c
        fa = "Auto" if state.fan == Fan.AUTO else "Silent" if state.fan == Fan.SILENT else str(state.fan.value - 2)
        if first:
            print("  %s  %s  %d°C  fan=%s\n  %s" % (p, m, t, fa, menu), end="", flush=True)
            first = False
        else:
            print("\033[2A\r  %s  %s  %d°C  fan=%s   \n  %s" % (p, m, t, fa, menu), end="", flush=True)

        k = getkey()
        if k.lower() == "q":
            print("\n")
            break
        if k == "\r" or k == "\n":
            print("\n  Sending...", end="", flush=True)
            if send_state(state):
                print(" OK.")
            else:
                print("\n\a\a\a  WARNING: decode != sent  \a\a\a")
            continue
        if k == " ":
            state.set_power(not state.power)
            continue
        if k in FAN_KEY:
            state.set_fan(FAN_KEY[k])
            continue
        if k.lower() in MODE_KEY:
            state.set_mode(MODE_KEY[k.lower()])
            continue
        if k == "UP":
            state.set_temp(state.temp_c + 1)
            continue
        if k == "DOWN":
            state.set_temp(state.temp_c - 1)
            continue


if __name__ == "__main__":
    main()
