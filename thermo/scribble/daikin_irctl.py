#!/usr/bin/env python3
"""Minimal interactive Daikin IR control for Pi Zero 2. State + one-letter menu; Enter sends via ir-ctl.

Keys: 0-5 fan | h/c/f/d/a mode | Space power | ↑↓ temp | Enter send.
After send, decodes and warns if decode != sent.
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import tempfile
import termios
import tty

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "onboard"))
from heatpumpirctl import Fan, Mode, State
from heatpumpirctl import ARC452A9 as proto

LIRC_TX = "/dev/lirc0"
LIRC_RX = "/dev/lirc1"

FAN_KEY = {"0": Fan.AUTO, "`": Fan.SILENT, "1": Fan.F1, "2": Fan.F2, "3": Fan.F3, "4": Fan.F4, "5": Fan.F5}
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
    except (FileNotFoundError, OSError) as e:
        print(f"Error (ir-ctl or device): {e}")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Error sending state: {e}")
        return False
    finally:
        os.unlink(path)
    return proto.round_trip_ok(state)


def listen_for_ir() -> State | None:
    """Listen to IR receiver until / is pressed. Return decoded State or None."""
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        try:
            proc = subprocess.Popen(
                ["ir-ctl", "-d", LIRC_RX, "--receive", "--mode2", "--timeout", "200000"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except (FileNotFoundError, OSError) as e:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            print(f"\n  Error (ir-ctl or device): {e}", end="", flush=True)
            return None
        print("\n  Listening for IR... press / to stop", end="", flush=True)
        buffer: list[str] = []
        while True:
            r, _, _ = select.select([fd, proc.stdout], [], [], 0.25)
            if fd in r:
                c = sys.stdin.read(1)
                if c == "/":
                    break
            if proc.stdout in r:
                line = proc.stdout.readline()
                if not line:
                    break
                buffer.append(line)
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

    ir_text = "".join(buffer)
    f1_raw: list | None = None
    f3_raw: list | None = None
    for kind, raw in proto.iter_frames(ir_text):
        if kind == "f1":
            f1_raw = raw
        elif kind in ("f3", "f3~"):
            f3_raw = raw
    if f3_raw is None:
        return None
    return proto.load(f3_raw, f1_raw)


def main() -> None:
    state = State().set_power(False).set_mode(Mode.HEAT).set_temp(22).set_fan(Fan.AUTO)
    menu = "0 auto ` whisper 1-5 fan | h/c/f/d/a mode | Space power | ↑↓ temp | Enter send | ? listen / stop | q quit"

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
            print("\n  %s  %s  %d°C  fan=%s\n  %s" % (p, m, t, fa, menu), end="", flush=True)

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
        if k == "?":
            s = listen_for_ir()
            if s is not None:
                state = s
                print("\n  Learned from remote.", end="", flush=True)
            else:
                print("\n  No valid frames.", end="", flush=True)
            continue


if __name__ == "__main__":
    main()
