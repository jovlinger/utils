#!/usr/bin/env python3
"""Throwaway: ask the knob for its current state.

Sends "query" and prints the firmware's reply. The reply is a live read
of the backlight pin and the awake flag. It does not infer those from
older log lines.
"""

from __future__ import annotations

import os
import select
import sys
import termios
import time
from typing import Dict, List


PORT = "/dev/cu.usbmodem1101"
BAUD = termios.B115200
WAIT_S = 3.0


def _open(path: str) -> int:
    fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    attrs = termios.tcgetattr(fd)
    attrs[0] = attrs[0] & ~termios.HUPCL
    attrs[2] = (attrs[2] | termios.CLOCAL | termios.CREAD) & ~termios.CRTSCTS
    attrs[4] = BAUD
    attrs[5] = BAUD
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def _query(path: str) -> str:
    fd = _open(path)
    try:
        deadline = time.time() + 0.2
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                os.read(fd, 4096)
        os.write(fd, b"query\n")
        deadline = time.time() + WAIT_S
        buf = b""
        while time.time() < deadline:
            ready, _, _ = select.select([fd], [], [], 0.2)
            if not ready:
                continue
            buf += os.read(fd, 4096)
            text = buf.decode("utf-8", "replace").replace("\r", "\n")
            parts = text.split("\n")
            complete = parts if text.endswith("\n") else parts[:-1]
            for line in complete:
                if line.startswith("query "):
                    return line.strip()
            if len(buf) > 8192:
                buf = buf[-4096:]
        return ""
    finally:
        os.close(fd)


def _fields(line: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    for tok in line.split():
        if "=" not in tok:
            continue
        key, value = tok.split("=", 1)
        found[key] = value
    return found


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else PORT
    order: List[str] = [
        "backlight",
        "awake",
        "idle_ms",
        "idle_sleep",
        "cpu_sleep",
        "wifi",
        "player",
        "volume",
        "system_mv",
        "power_w",
    ]
    try:
        line = _query(path)
    except OSError as exc:
        print("port: %s" % path)
        print("error: %s" % exc)
        return 1
    print("port: %s" % path)
    if not line:
        print("error: no query reply")
        return 1
    fields = _fields(line)
    for key in order:
        print("%s: %s" % (key, fields.get(key, "missing")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
