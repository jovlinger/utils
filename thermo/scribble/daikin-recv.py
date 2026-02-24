#!/usr/bin/env python3
"""Receive IR from the Daikin remote and attempt to decode to 3-frame Daikin bytes.

Runs on Pi Zero 2W with ANAVI IR pHAT: reads from /dev/lirc1 (RX) via ir-ctl.
Uses pulse-distance decoding; frame lengths 8, 8, 19 bytes (blafois/Daikin-IR-Reverse).
Checksum = sum of bytes in frame & 0xff. We may need to adjust thresholds for your remote.

Usage:
  ir-ctl -d /dev/lirc1 --receive | python3 daikin-recv.py
  or (if your system supports it):
  python3 daikin-recv.py   # runs ir-ctl as subprocess and reads stdin
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from typing import Iterator, List, Optional, Sequence, Tuple

# LIRC RX device on Pi Zero 2W with ANAVI IR pHAT (GPIO 17).
LIRC_RX: str = "/dev/lirc1"

# Pulse-distance thresholds (microseconds). Daikin: HIGH ~430µs, 0 ~420µs, 1 ~1286µs.
# Inter-frame gap typically 30ms+. Start: pulse ~3400µs, space ~1750µs (optional).
PULSE_MIN, PULSE_MAX = 250, 650
SPACE_ZERO_MIN, SPACE_ZERO_MAX = 300, 550
SPACE_ONE_MIN, SPACE_ONE_MAX = 1000, 1600
GAP_MIN: int = 15_000
START_PULSE_MIN, START_PULSE_MAX = 2500, 4500
START_SPACE_MIN, START_SPACE_MAX = 1200, 2200
# Lines arriving this long after the previous: reset state and skip feeding (likely phantom/EOF).
GAP_LINE_SEC: float = 2.0
DEBUG_RECV: bool = False  # stderr: when lines/pairs received, even if not parsed


def parse_line(line: str) -> Optional[Tuple[str, int]]:
    """Return ('pulse', us) or ('space', us) or None. Accepts 'pulse N', 'space N', or bare N (mode2)."""
    line = line.strip()
    if not line:
        return None
    m = re.match(r"(pulse|space)\s+(\d+)", line, re.I)
    if m:
        return m.group(1).lower(), int(m.group(2))
    if line.isdigit():
        # Mode2-style: single number; caller must assign kind via alternating state.
        return ("_mode2_", int(line))
    return None


def iter_pulse_space_pairs(line: str) -> Iterator[Tuple[str, int]]:
    """Yield (kind, us) from one line. Handles multi-token lines: 'pulse 3400 space 1750 ...' or '3400 1750 ...'."""
    tokens = line.strip().split()
    i = 0
    next_kind = "pulse"
    while i < len(tokens):
        t = tokens[i]
        if t.lower() in ("pulse", "space") and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            yield t.lower(), int(tokens[i + 1])
            i += 2
        elif t.isdigit():
            yield next_kind, int(t)
            next_kind = "space" if next_kind == "pulse" else "pulse"
            i += 1
        else:
            i += 1


def decode_bits(sequences: List[Tuple[int, int]]) -> List[int]:
    """Decode list of (pulse_us, space_us) into bits (LSB first), then bytes."""
    bits = []
    for pulse_us, space_us in sequences:
        if not (PULSE_MIN <= pulse_us <= PULSE_MAX):
            continue
        if SPACE_ZERO_MIN <= space_us <= SPACE_ZERO_MAX:
            bits.append(0)
        elif SPACE_ONE_MIN <= space_us <= SPACE_ONE_MAX:
            bits.append(1)
        # else: skip ambiguous
    # Bits are LSB first; 8 bits = 1 byte (LSB first within byte)
    bytes_out = []
    for i in range(0, len(bits), 8):
        chunk = bits[i : i + 8]
        if len(chunk) < 8:
            break
        byte_val = sum(b << j for j, b in enumerate(chunk))
        bytes_out.append(byte_val & 0xFF)
    return bytes_out


def checksum_ok(frame: Sequence[int]) -> bool:
    """Last byte of frame should equal sum of previous bytes & 0xff."""
    if len(frame) < 2:
        return False
    expected = sum(frame[:-1]) & 0xFF
    return frame[-1] == expected


def interpret_frames(f1: Sequence[int], f2: Sequence[int], f3: Sequence[int]) -> None:
    """Print human-readable summary of the three Daikin frames."""
    if len(f1) >= 5 and f1[4] == 0xC5:
        comfort = "comfort on" if len(f1) > 6 and (f1[6] & 0x10) else "comfort off"
        print(f"  Frame1: 0xc5  {comfort}")
    if len(f2) >= 5 and f2[4] == 0x42:
        print("  Frame2: 0x42 (fixed)")
    if len(f3) >= 19:
        b5 = f3[5]
        mode_nib = (b5 >> 4) & 0x0F
        power = "ON" if (b5 & 0x01) else "OFF"
        mode = {"0": "AUTO", "2": "DRY", "3": "COOL", "4": "HEAT", "6": "FAN"}.get(
            str(mode_nib), f"0x{mode_nib:x}"
        )
        temp_c = f3[6] // 2 if 10 <= f3[6] // 2 <= 30 else None
        fan_byte = f3[8]
        fan_nib = (fan_byte >> 4) & 0x0F
        swing = "swing" if (fan_byte & 0x0F) == 0x0F else "no swing"
        fan = (
            f"fan{fan_nib}"
            if 3 <= fan_nib <= 7
            else (
                "Auto"
                if fan_nib == 0xA
                else "Silent" if fan_nib == 0xB else f"0x{fan_nib:x}"
            )
        )
        powerful = (f3[0x0D] & 0x01) != 0 if len(f3) > 0x0D else False
        econo = (f3[0x10] & 0x0F) == 0x04 if len(f3) > 0x10 else False
        print(
            f"  Frame3: power={power} mode={mode} temp={temp_c}C fan={fan} {swing} powerful={powerful} econo={econo}"
        )


def run_from_stdin() -> None:
    """Read ir-ctl style lines from stdin and decode Daikin 3-frame sequences."""
    current: List[Tuple[int, int]] = []
    in_gap = True
    last_was_pulse = False
    last_pulse_us = 0
    frame1: Optional[List[int]] = None
    frame2: Optional[List[int]] = None
    frame3: Optional[List[int]] = None

    def flush_current() -> None:
        nonlocal frame1, frame2, frame3
        if not current:
            return
        raw = decode_bits(current)
        if len(raw) == 8 and checksum_ok(raw):
            if raw[4] == 0xC5:
                frame1 = raw
            elif raw[4] == 0x42:
                frame2 = raw
        elif len(raw) == 19 and checksum_ok(raw):
            frame3 = raw
            if frame1 is not None and frame2 is not None:
                print("Daikin 3-frame:")
                print("  F1:", " ".join(f"{b:02x}" for b in frame1))
                print("  F2:", " ".join(f"{b:02x}" for b in frame2))
                print("  F3:", " ".join(f"{b:02x}" for b in frame3))
                interpret_frames(frame1, frame2, frame3)
            frame1 = frame2 = frame3 = None

    last_line_time = 0.0
    for line in sys.stdin:
        now = time.time()
        if last_line_time > 0 and (now - last_line_time) > GAP_LINE_SEC:
            if DEBUG_RECV:
                sys.stderr.write("[daikin-recv] gap > %.1fs, reset and skip line\n" % GAP_LINE_SEC)
                sys.stderr.flush()
            flush_current()
            current.clear()
            in_gap = True
            last_line_time = now
            continue
        last_line_time = now
        npairs = 0
        for kind, us in iter_pulse_space_pairs(line):
            npairs += 1
            if kind == "pulse":
                if in_gap and START_PULSE_MIN <= us <= START_PULSE_MAX:
                    current.clear()
                    in_gap = False
                last_pulse_us = us
                last_was_pulse = True
                continue
            if kind == "space":
                if us >= GAP_MIN:
                    flush_current()
                    current.clear()
                    in_gap = True
                elif last_was_pulse and PULSE_MIN <= last_pulse_us <= PULSE_MAX:
                    current.append((last_pulse_us, us))
                    in_gap = False
                last_was_pulse = False
        if DEBUG_RECV and npairs > 0:
            sys.stderr.write("[daikin-recv] line len=%d -> %d pairs\n" % (len(line), npairs))
            sys.stderr.flush()

    flush_current()


def run_subprocess() -> None:
    """Spawn ir-ctl --receive and run decoder on its stdout."""
    # Force line-buffered stdout so we see each pulse/space line as it arrives (ir-ctl
    # uses full buffer when stdout is a pipe, so otherwise we'd see nothing until 4KB+).
    for cmd in (
        ["stdbuf", "-oL", "ir-ctl", "-d", LIRC_RX, "--receive"],
        ["ir-ctl", "-d", LIRC_RX, "--receive"],
    ):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            break
        except FileNotFoundError:
            continue
    else:
        raise FileNotFoundError("ir-ctl not found in PATH")
    # Re-use decoder logic by feeding lines
    current: List[Tuple[int, int]] = []
    in_gap = True
    last_was_pulse = False
    last_pulse_us = 0
    frame1: Optional[List[int]] = None
    frame2: Optional[List[int]] = None
    frame3: Optional[List[int]] = None

    def flush_current() -> None:
        nonlocal frame1, frame2, frame3
        if not current:
            return
        raw = decode_bits(current)
        if len(raw) == 8 and checksum_ok(raw):
            if raw[4] == 0xC5:
                frame1 = raw
            elif raw[4] == 0x42:
                frame2 = raw
        elif len(raw) == 19 and checksum_ok(raw):
            frame3 = raw
            if frame1 is not None and frame2 is not None:
                print("Daikin 3-frame:")
                print("  F1:", " ".join(f"{b:02x}" for b in frame1))
                print("  F2:", " ".join(f"{b:02x}" for b in frame2))
                print("  F3:", " ".join(f"{b:02x}" for b in frame3))
                interpret_frames(frame1, frame2, frame3)
            frame1 = frame2 = frame3 = None

    last_line_time: float = 0.0
    try:
        for line in proc.stdout:
            now = time.time()
            if last_line_time > 0 and (now - last_line_time) > GAP_LINE_SEC:
                if DEBUG_RECV:
                    sys.stderr.write("[daikin-recv] gap > %.1fs, reset and skip line\n" % GAP_LINE_SEC)
                    sys.stderr.flush()
                flush_current()
                current.clear()
                in_gap = True
                last_line_time = now
                continue
            last_line_time = now
            npairs = 0
            for kind, us in iter_pulse_space_pairs(line):
                npairs += 1
                if kind == "pulse":
                    if in_gap and START_PULSE_MIN <= us <= START_PULSE_MAX:
                        current.clear()
                        in_gap = False
                    last_pulse_us = us
                    last_was_pulse = True
                    continue
                if kind == "space":
                    if us >= GAP_MIN:
                        flush_current()
                        current.clear()
                        in_gap = True
                elif last_was_pulse and PULSE_MIN <= last_pulse_us <= PULSE_MAX:
                    current.append((last_pulse_us, us))
                    in_gap = False
                last_was_pulse = False
            if DEBUG_RECV and npairs > 0:
                sys.stderr.write("[daikin-recv] line len=%d -> %d pairs\n" % (len(line), npairs))
                sys.stderr.flush()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except KeyboardInterrupt:
            pass
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait()
            except KeyboardInterrupt:
                pass
    flush_current()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        run_from_stdin()
    else:
        print("Listening on", LIRC_RX, "(Ctrl+C to stop)...")
        run_subprocess()
