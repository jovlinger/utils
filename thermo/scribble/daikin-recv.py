#!/usr/bin/env python3
"""Receive IR from the Daikin remote (ARC452A9); decode to human-readable frame.

Pi Zero 2W + ANAVI IR pHAT (/dev/lirc1). Prompt for description (Enter=reuse,
Ctrl-C=exit), listen for one unit per description, print decoded fields.

Captures raw ir-ctl lines to scribble/captures/daikin_recv_<timestamp>.log
(one file per run, plain text, easy to grep/diff).
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterator, List, Optional, Sequence, Tuple

LIRC_RX: str = "/dev/lirc1"

PULSE_MIN, PULSE_MAX = 250, 650
SPACE_ZERO_MIN, SPACE_ZERO_MAX = 300, 550
SPACE_ONE_MIN, SPACE_ONE_MAX = 1000, 1600
GAP_MIN: int = 5_000
START_PULSE_MIN, START_PULSE_MAX = 2500, 4500
START_SPACE_MIN, START_SPACE_MAX = 1200, 2200
PAUSE_SEC: float = 0.5
READ_TIMEOUT_SEC: float = 1.0
GAP_LINE_SEC: float = 2.0
DEBUG_RECV: bool = True

_SCRIBBLE_DIR = os.path.dirname(os.path.abspath(__file__))
_CAPTURES_DIR = os.path.join(_SCRIBBLE_DIR, "captures")

MODE_NAMES = {0: "AUTO", 2: "DRY", 3: "COOL", 4: "HEAT", 6: "FAN"}
FAN_NAMES = {
    3: "1/5",
    4: "2/5",
    5: "3/5",
    6: "4/5",
    7: "5/5",
    0xA: "Auto",
    0xB: "Silent",
}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# ---------------------------------------------------------------------------
# Capture log (plain text)
# ---------------------------------------------------------------------------


def _open_capture_log() -> Any:
    os.makedirs(_CAPTURES_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H%M%S")
    path = os.path.join(_CAPTURES_DIR, "daikin_recv_%s.log" % ts)
    f = open(path, "a")
    sys.stderr.write("[%s] capture log: %s\n" % (_ts(), path))
    sys.stderr.flush()
    return f


def _log_unit(log_file: Any, description: str, lines: List[str]) -> None:
    log_file.write(
        "# %s  description=%s  lines=%d\n"
        % (datetime.now(timezone.utc).isoformat(), description, len(lines))
    )
    for line in lines:
        log_file.write(line if line.endswith("\n") else line + "\n")
    log_file.write("\n")
    log_file.flush()


# ---------------------------------------------------------------------------
# Tokenising ir-ctl output
# ---------------------------------------------------------------------------


def _token_number(t: str) -> Optional[int]:
    if t.isdigit():
        return int(t)
    m = re.search(r"\d+", t)
    return int(m.group(0)) if m else None


def iter_pulse_space_pairs(line: str) -> Iterator[Tuple[str, int]]:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return
    tokens = stripped.split()
    first = tokens[0].lower()
    # mode2 "timeout N" → treat as a space (it IS the inter-frame gap)
    if first == "timeout" and len(tokens) > 1:
        n = _token_number(tokens[1])
        if n is not None:
            yield "space", n
        return
    # mode2 "carrier N" → metadata, skip
    if first in ("carrier", "scancode"):
        return
    i = 0
    next_kind = "pulse"
    while i < len(tokens):
        t = tokens[i]
        if t.lower() in ("pulse", "space") and i + 1 < len(tokens):
            n = _token_number(tokens[i + 1])
            if n is not None:
                yield t.lower(), n
                i += 2
                continue
        n = _token_number(t)
        if n is not None:
            yield next_kind, n
            next_kind = "space" if next_kind == "pulse" else "pulse"
            i += 1
            continue
        i += 1


# ---------------------------------------------------------------------------
# Unit splitting (by pause on ir-ctl stdout)
# ---------------------------------------------------------------------------


def read_units_by_pause(
    stream: Any,
    pause_sec: float = PAUSE_SEC,
    read_timeout: float = READ_TIMEOUT_SEC,
) -> Iterator[List[str]]:
    """Yield units (list of lines) split by pause >= pause_sec with no data."""
    buffer: List[str] = []
    last_activity: float = 0.0
    fd = stream.fileno()
    while True:
        r, _, _ = select.select([fd], [], [], read_timeout)
        now = time.time()
        if not r:
            idle = now - last_activity
            if buffer and idle > pause_sec:
                if DEBUG_RECV:
                    sys.stderr.write(
                        "[%s] unit ended: idle %.3fs -> %d lines\n"
                        % (_ts(), idle, len(buffer))
                    )
                    sys.stderr.flush()
                yield buffer
                buffer = []
            continue
        line = stream.readline()
        if not line:
            break
        now = time.time()
        gap = now - last_activity
        if buffer and gap > pause_sec:
            if DEBUG_RECV:
                sys.stderr.write(
                    "[%s] unit ended: gap %.3fs before new line -> %d lines\n"
                    % (_ts(), gap, len(buffer))
                )
                sys.stderr.flush()
            yield buffer
            buffer = []
        buffer.append(line)
        last_activity = now
        if DEBUG_RECV:
            sys.stderr.write("[%s] got line len=%d\n" % (_ts(), len(line)))
            sys.stderr.flush()
    if buffer:
        if DEBUG_RECV:
            sys.stderr.write(
                "[%s] unit ended: EOF -> %d lines\n" % (_ts(), len(buffer))
            )
            sys.stderr.flush()
        yield buffer


# ---------------------------------------------------------------------------
# Bit / byte decoding
# ---------------------------------------------------------------------------


def lines_to_pairs(lines: List[str]) -> List[Tuple[int, int]]:
    pairs: List[Tuple[int, int]] = []
    last_pulse_us: Optional[int] = None
    for line in lines:
        for kind, us in iter_pulse_space_pairs(line):
            if kind in ("pulse", "_mode2_") and last_pulse_us is None:
                last_pulse_us = us
            elif kind == "pulse":
                last_pulse_us = us
            elif kind == "space" and last_pulse_us is not None:
                pairs.append((last_pulse_us, us))
                last_pulse_us = None
    return pairs


def split_at_gaps(
    pairs: List[Tuple[int, int]], gap_min: int = GAP_MIN
) -> List[List[Tuple[int, int]]]:
    sub: List[List[Tuple[int, int]]] = []
    cur: List[Tuple[int, int]] = []
    for p, s in pairs:
        cur.append((p, s))
        if s >= gap_min:
            sub.append(cur)
            cur = []
    if cur:
        sub.append(cur)
    return sub


def decode_bits(pairs: List[Tuple[int, int]]) -> List[int]:
    bits: List[int] = []
    for pulse_us, space_us in pairs:
        if not (PULSE_MIN <= pulse_us <= PULSE_MAX):
            continue
        if SPACE_ZERO_MIN <= space_us <= SPACE_ZERO_MAX:
            bits.append(0)
        elif SPACE_ONE_MIN <= space_us <= SPACE_ONE_MAX:
            bits.append(1)
    out: List[int] = []
    for i in range(0, len(bits), 8):
        chunk = bits[i : i + 8]
        if len(chunk) < 8:
            break
        out.append(sum(b << j for j, b in enumerate(chunk)) & 0xFF)
    return out


def checksum_ok(frame: Sequence[int]) -> bool:
    if len(frame) < 2:
        return False
    return frame[-1] == (sum(frame[:-1]) & 0xFF)


# ---------------------------------------------------------------------------
# Frame classification and decoding
# ---------------------------------------------------------------------------


def classify_frame(raw: List[int]) -> Optional[str]:
    """Return 'f1', 'f2', 'f3', or 'f3~' (truncated F3) for a Daikin frame, else None."""
    has_header = len(raw) >= 5 and raw[:3] == [0x11, 0xDA, 0x27]
    chk = checksum_ok(raw)
    if not has_header:
        return None
    if len(raw) == 8 and chk:
        if raw[4] == 0xC5:
            return "f1"
        if raw[4] == 0x42:
            return "f2"
        return "f1"  # ARC452A9 variant (byte4=0x00)
    if len(raw) == 19:
        return "f3" if chk else "f3~"
    if 9 <= len(raw) <= 18:
        return "f3~"
    return None


def try_split_combined(raw: List[int]) -> Optional[List[Tuple[str, List[int]]]]:
    """If raw contains multiple concatenated Daikin frames, split at header boundaries."""
    HEADER = [0x11, 0xDA, 0x27]
    positions = [i for i in range(len(raw)) if raw[i : i + 3] == HEADER]
    if len(positions) < 2:
        return None
    result: List[Tuple[str, List[int]]] = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(raw)
        frame = raw[pos:end]
        kind = classify_frame(frame)
        if kind:
            result.append((kind, frame))
    return result if result else None


def decode_f1(f1: List[int]) -> List[str]:
    """Decode Frame 1 (8 bytes). Returns list of 'key=value' strings."""
    parts: List[str] = []
    comfort = bool(f1[6] & 0x10) if len(f1) > 6 else False
    parts.append("comfort=%s" % ("on" if comfort else "off"))
    if f1[3] == 0xF0:
        parts.append("variant=ARC452A9")
    elif f1[3] != 0x00:
        parts.append("byte3=0x%02x" % f1[3])
    if f1[4] not in (0x00, 0xC5):
        parts.append("id=0x%02x" % f1[4])
    return parts


def decode_f3(f3: List[int]) -> List[str]:
    """Decode Frame 3 per blafois layout. Safe for truncated frames (>= 9 bytes)."""
    n = len(f3)
    parts: List[str] = []

    if n > 5:
        b5 = f3[5]
        mode_nib = (b5 >> 4) & 0x0F
        parts.append("power=%s" % ("ON" if (b5 & 0x01) else "OFF"))
        parts.append("mode=%s" % MODE_NAMES.get(mode_nib, "0x%x" % mode_nib))

    if n > 6:
        temp_raw = f3[6]
        temp_c = temp_raw / 2
        if 10 <= temp_c <= 32:
            parts.append("temp=%.0fC" % temp_c)
        else:
            parts.append("temp_raw=0x%02x" % temp_raw)

    if n > 8:
        fan_byte = f3[8]
        fan_nib = (fan_byte >> 4) & 0x0F
        swing_nib = fan_byte & 0x0F
        parts.append("fan=%s" % FAN_NAMES.get(fan_nib, "0x%x" % fan_nib))
        parts.append("swing=%s" % ("on" if swing_nib == 0x0F else "off"))

    if n > 0x0C:
        b5 = f3[5]
        timer_on = bool(b5 & 0x02)
        timer_off = bool(b5 & 0x04)
        if timer_on:
            timer_min = (f3[0x0B] & 0x0F) << 8 | f3[0x0A]
            parts.append("timer_on=%dm" % timer_min if timer_min else "timer_on")
        if timer_off:
            timer_min = (f3[0x0C] << 4) | (f3[0x0B] >> 4)
            parts.append("timer_off=%dm" % timer_min if timer_min else "timer_off")

    if n > 0x0D:
        parts.append("powerful=%s" % ("on" if (f3[0x0D] & 0x01) else "off"))

    if n > 0x10:
        parts.append("econo=%s" % ("on" if (f3[0x10] & 0x04) else "off"))

    if n > 0x0F:
        parts.append("byte0f=0x%02x" % f3[0x0F])

    return parts


# ---------------------------------------------------------------------------
# parse_unit: split at gaps, classify, decode
# ---------------------------------------------------------------------------


def _hex(raw: Sequence[int]) -> str:
    return " ".join("%02x" % b for b in raw)


def parse_unit(lines: List[str], description: str = "") -> None:
    pairs = lines_to_pairs(lines)
    t = _ts()
    if description:
        print("[%s] Description: %s" % (t, description))

    if not pairs:
        print("[%s] (no data)" % t)
        return

    sub_frame_pairs = split_at_gaps(pairs)
    frames: List[Tuple[str, List[int]]] = []
    for sf_pairs in sub_frame_pairs:
        raw = decode_bits(sf_pairs)
        if not raw:
            continue
        kind = classify_frame(raw)
        if kind:
            frames.append((kind, raw))
        else:
            combined = try_split_combined(raw)
            if combined:
                frames.extend(combined)
            elif len(raw) >= 2:
                frames.append(("?", raw))

    total_bytes = sum(len(r) for _, r in frames)
    n_frames = len(frames)
    if n_frames == 0:
        print("[%s] (noise — %d pairs, no valid frames)" % (t, len(pairs)))
        return

    print("[%s] %d frame(s), %d bytes" % (t, n_frames, total_bytes))

    decoded_count = 0
    for kind, raw in frames:
        if kind == "f1":
            parts = decode_f1(raw)
            print("[%s]   F1: %s  [%s]" % (_ts(), " ".join(parts), _hex(raw)))
            decoded_count += len(raw)
        elif kind == "f2":
            print("[%s]   F2: (fixed)  [%s]" % (_ts(), _hex(raw)))
            decoded_count += len(raw)
        elif kind in ("f3", "f3~"):
            parts = decode_f3(raw)
            tag = "F3" if kind == "f3" else "F3~(%d/%d)" % (len(raw), 19)
            print("[%s]   %s: %s  [%s]" % (_ts(), tag, " ".join(parts), _hex(raw)))
            decoded_count += len(raw)
        else:
            chk = checksum_ok(raw)
            print("[%s]   ?(%d): %s chk=%s" % (_ts(), len(raw), _hex(raw), chk))

    opaque = total_bytes - decoded_count
    if opaque > 0:
        print("[%s]   Opaque: %d of %d bytes" % (_ts(), opaque, total_bytes))


# ---------------------------------------------------------------------------
# run_from_stdin (piped mode, used by test)
# ---------------------------------------------------------------------------


def run_from_stdin() -> None:
    """Read ir-ctl style lines from stdin and decode Daikin frame sequences."""
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
        kind = classify_frame(raw) if raw else None
        if kind == "f1":
            frame1 = raw
        elif kind == "f2":
            frame2 = raw
        elif kind == "f3":
            frame3 = raw
            if frame1 is not None and frame2 is not None:
                print("Daikin 3-frame:")
                print("  F1:", " ".join(f"{b:02x}" for b in frame1))
                print("  F2:", " ".join(f"{b:02x}" for b in frame2))
                print("  F3:", " ".join(f"{b:02x}" for b in frame3))
                parts = decode_f3(frame3)
                print("  Frame3:", " ".join(parts))
            frame1 = frame2 = frame3 = None

    last_line_time = 0.0
    for line in sys.stdin:
        now = time.time()
        if last_line_time > 0 and (now - last_line_time) > GAP_LINE_SEC:
            flush_current()
            current.clear()
            in_gap = True
            last_line_time = now
            continue
        last_line_time = now
        for kind, us in iter_pulse_space_pairs(line):
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

    flush_current()


# ---------------------------------------------------------------------------
# run_subprocess: simple for-loop, description prompt, Ctrl-C to exit
# ---------------------------------------------------------------------------


def run_subprocess() -> None:
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

    log_file = _open_capture_log()
    unit_iter = read_units_by_pause(proc.stdout)
    last_desc: Optional[str] = None
    try:
        while True:
            try:
                sys.stdout.write("Description (Enter=reuse, Ctrl-C=exit): ")
                sys.stdout.flush()
                desc = sys.stdin.readline()
                if desc is None:
                    break
                desc = desc.strip()
                if not desc:
                    if last_desc is None:
                        break
                    desc = last_desc
                else:
                    last_desc = desc
            except KeyboardInterrupt:
                break

            unit = next(unit_iter, None)
            if unit is None:
                sys.stderr.write("[%s] EOF from ir-ctl\n" % _ts())
                sys.stderr.flush()
                break

            _log_unit(log_file, desc, unit)
            parse_unit(unit, desc)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stderr.write("[%s] exiting\n" % _ts())
        sys.stderr.flush()
        log_file.close()
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait()


def run_from_log(path: str) -> None:
    """Parse a capture log file and decode each record."""
    with open(path) as f:
        desc = ""
        data_lines: List[str] = []
        for line in f:
            if line.startswith("#"):
                if data_lines:
                    parse_unit(data_lines, desc)
                    data_lines = []
                m = re.search(r"description=(.+?)\s{2,}lines=", line)
                desc = m.group(1) if m else ""
            elif line.strip():
                data_lines.append(line)
        if data_lines:
            parse_unit(data_lines, desc)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        run_from_stdin()
    elif len(sys.argv) > 2 and sys.argv[1] == "--parse-log":
        run_from_log(sys.argv[2])
    else:
        print("Listening on", LIRC_RX, "(Ctrl+C to stop)...")
        run_subprocess()
