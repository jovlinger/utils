#!/usr/bin/env python3
"""Host-side hardware debug CLI for Pi Zero onboard (LIRC IR RX)."""

from __future__ import annotations

import argparse
import os
import select
import struct
import sys
from typing import Iterable, Optional, Sequence, TextIO

LIRC_RX = (os.environ.get("IR_RX_DEVICE") or "/dev/lirc1").strip()
LIRC_TX = (os.environ.get("IR_DEVICE") or "/dev/lirc0").strip()

HELP_TEXT = """Thermo hardware debug commands:
  help
  pins
  gpio set <pin> hi|lo
  gpio read <pin>
  ir promisc on|off
HAT continuity (Pico2W / ESP32-S3): short net to 3V3, then gpio read <pin>.
Pi Zero: GPIO HAT debug is not supported; use ir promisc with /dev/lirc1.
"""


def parse_command(line: str) -> tuple[str, ...]:
    return tuple(part for part in line.strip().lower().split() if part)


def write_help(out: TextIO) -> None:
    out.write(HELP_TEXT)


def write_pins(out: TextIO) -> None:
    out.write("platform pizero2w (no GPIO HAT debug)\n")
    out.write("ir_tx %s\n" % LIRC_TX)
    out.write("ir_rx %s\n" % LIRC_RX)


def write_err(out: TextIO, message: str) -> None:
    out.write("ERR %s\n" % message)


def write_ok(out: TextIO, message: str) -> None:
    out.write("OK %s\n" % message)


def handle_command(parts: Sequence[str], out: TextIO) -> bool:
    if not parts:
        return True
    head = parts[0]
    if head in {"help", "?"}:
        write_help(out)
        return True
    if head == "pins":
        write_pins(out)
        return True
    if head == "gpio":
        write_err(out, "gpio not supported on pizero2w (use Pico2W USB debug)")
        return True
    if head == "ir" and len(parts) == 3 and parts[1] == "promisc":
        if parts[2] in {"on", "1"}:
            return False
        if parts[2] in {"off", "0"}:
            write_ok(out, "ir promisc off")
            return True
    write_err(out, "unknown command (try help)")
    return True


def stream_lirc_events(rx_path: str, out: TextIO) -> int:
    try:
        rx_fd = os.open(rx_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError as exc:
        write_err(out, "open %s failed: %s" % (rx_path, exc))
        return 1
    write_ok(out, "ir promisc on")
    out.flush()
    try:
        while True:
            ready, _, _ = select.select([sys.stdin, rx_fd], [], [], 0.2)
            if sys.stdin in ready:
                line = sys.stdin.readline()
                if not line:
                    break
                parts = parse_command(line)
                if parts[:3] == ("ir", "promisc", "off"):
                    write_ok(out, "ir promisc off")
                    out.flush()
                    break
            if rx_fd in ready:
                data = os.read(rx_fd, 16)
                if len(data) >= 8:
                    value = struct.unpack("I", data[:4])[0]
                    high = bool(value & 0x0100_0000)
                    duration_us = value & 0x00FF_FFFF
                    level = "hi" if high else "lo"
                    out.write("ir edge %s us %s\n" % (duration_us, level))
                    out.flush()
    finally:
        os.close(rx_fd)
    return 0


def repl(out: TextIO) -> int:
    write_ok(out, "Thermo Pi Zero hwdebug (type help)")
    out.flush()
    for line in sys.stdin:
        parts = parse_command(line)
        if not handle_command(parts, out):
            return stream_lirc_events(LIRC_RX, out)
        out.flush()
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Thermo Pi Zero hardware debug CLI")
    parser.add_argument(
        "command",
        nargs="*",
        help="Optional one-shot command, e.g. pins or ir promisc on",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    out = sys.stdout
    if args.command:
        parts = tuple(part.lower() for part in args.command)
        if not handle_command(parts, out):
            return stream_lirc_events(LIRC_RX, out)
        out.flush()
        return 0
    return repl(out)


if __name__ == "__main__":
    raise SystemExit(main())
