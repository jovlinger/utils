#!/usr/bin/env python3
"""Receive IR from the Daikin remote; decode to human-readable frame (mode, temp, fan, ...).

Pi Zero 2W + ANAVI IR pHAT (/dev/lirc1). Prompt for description (Enter=reuse, empty=exit),
listen for one unit, report decoded fields + opaque byte count. Two units per description
= error (gap too short). Ctrl-C exits.
"""

from __future__ import annotations

import os
import pickle
import queue
import re
import select
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Any, Iterator, List, Optional, Sequence, Tuple

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
# Pause between "units" (e.g. keypresses): no data for this long -> yield unit.
# Use ~2s so one keypress (often 2 lines) stays one unit; phantom data later is separate.
PAUSE_SEC: float = 2.0
# Select timeout so we never block forever.
READ_TIMEOUT_SEC: float = 1.0
# For --stdin line loop: gap after this many sec -> reset and skip line (phantom/EOF).
GAP_LINE_SEC: float = 2.0
# Subprocess mode: wait up to this long for one unit after description entered.
RECV_TIMEOUT_SEC: float = 10.0
# Always print debug to stderr so you see data flow.
DEBUG_RECV: bool = True


def _ts() -> str:
    """Current time prefix for log/parse output (HH:MM:SS.fff)."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


# Capture file: scribble/captures/daikin_recv_YYYY-MM-DD.pkl (binary name + date).
_SCRIBBLE_DIR = os.path.dirname(os.path.abspath(__file__))
_CAPTURES_DIR = os.path.join(_SCRIBBLE_DIR, "captures")


def _capture_path_for_date() -> str:
    """Path for today's capture file: scribble/captures/daikin_recv_YYYY-MM-DD.pkl."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(_CAPTURES_DIR, "daikin_recv_%s.pkl" % date_str)


def _load_capture_session(path: str) -> List[Any]:
    """Load session list from pickle file; return [] if missing or invalid."""
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except (pickle.PickleError, OSError):
        return []


def _append_and_save_capture(path: str, session: List[Any], record: Any) -> None:
    """Append one record to session and save to path."""
    session.append(record)
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "wb") as f:
        pickle.dump(session, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())


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


def _token_number(t: str) -> Optional[int]:
    """Extract integer from token; accept plain digits or trailing junk (e.g. '3400,' or '3400us')."""
    if t.isdigit():
        return int(t)
    m = re.search(r"\d+", t)
    return int(m.group(0)) if m else None


def iter_pulse_space_pairs(line: str) -> Iterator[Tuple[str, int]]:
    """Yield (kind, us) from one line. Handles 'pulse 3400 space 1750 ...', '3400 1750 ...', or tokens with trailing junk."""
    tokens = line.strip().split()
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


def read_units_by_pause(
    stream: Any,
    pause_sec: float = PAUSE_SEC,
    read_timeout: float = READ_TIMEOUT_SEC,
) -> Iterator[List[str]]:
    """Yield units (list of lines) split by pause: no data for pause_sec -> yield buffer."""
    buffer: List[str] = []
    last_activity: float = 0.0
    fd = stream.fileno()
    while True:
        r, _, _ = select.select([fd], [], [], read_timeout)
        now = time.time()
        if not r:
            idle = now - last_activity
            if buffer and idle > pause_sec:
                unit = buffer
                buffer = []
                if DEBUG_RECV:
                    sys.stderr.write(
                        "[%s] [daikin-recv] unit ended: no data for %.3fs (>= PAUSE_SEC %.1f) -> yielded %d lines\n"
                        % (_ts(), idle, pause_sec, len(unit))
                    )
                    sys.stderr.flush()
                yield unit
            continue
        line = stream.readline()
        if not line:
            break
        now = time.time()
        gap = now - last_activity
        if buffer and gap > pause_sec:
            unit = buffer
            buffer = []
            if DEBUG_RECV:
                sys.stderr.write(
                    "[%s] [daikin-recv] unit ended: gap since last line %.3fs (>= PAUSE_SEC %.1f) before new line -> yielded %d lines\n"
                    % (_ts(), gap, pause_sec, len(unit))
                )
                sys.stderr.flush()
            yield unit
        buffer.append(line)
        last_activity = now
        if DEBUG_RECV:
            sys.stderr.write(
                "[%s] [daikin-recv] got line len=%d\n" % (_ts(), len(line))
            )
            sys.stderr.flush()
    if buffer:
        if DEBUG_RECV:
            sys.stderr.write(
                "[%s] [daikin-recv] unit ended: EOF -> yielded %d lines\n"
                % (_ts(), len(buffer))
            )
            sys.stderr.flush()
        yield buffer


def lines_to_pairs(lines: List[str]) -> List[Tuple[int, int]]:
    """Convert lines (ir-ctl format) to list of (pulse_us, space_us) for decode_bits."""
    pairs: List[Tuple[int, int]] = []
    next_kind = "pulse"
    last_pulse_us: Optional[int] = None
    for line in lines:
        for kind, us in iter_pulse_space_pairs(line):
            if kind == "_mode2_":
                kind = next_kind
                next_kind = "space" if next_kind == "pulse" else "pulse"
            if kind == "pulse":
                last_pulse_us = us
            elif kind == "space" and last_pulse_us is not None:
                pairs.append((last_pulse_us, us))
                last_pulse_us = None
    return pairs


def parse_unit(lines: List[str], description: str = "") -> None:
    """Parse one unit; print timestamped description, input correlation, decoded fields, and opaque N of M bytes."""
    n_lines = len(lines)
    line_lens = ", ".join(str(len(l)) for l in lines)
    pairs = lines_to_pairs(lines)
    raw = decode_bits(pairs) if pairs else []
    total = len(raw)
    t = _ts()
    if description:
        print("[%s] Description: %s" % (t, description))
    # Correlation: same line count and lengths as "got line len=..." so total= matches later.
    print(
        "[%s] input: %d lines (len %s) -> total=%d bytes"
        % (t, n_lines, line_lens, total)
    )

    if not pairs:
        print("[%s] Decoded: (none — no pulse/space pairs)" % _ts())
        print("[%s] Opaque: 0 of 0 bytes" % _ts())
        return
    if not raw:
        print("[%s] Decoded: (none — pairs did not decode to bytes)" % _ts())
        print("[%s] Opaque: 0 of 0 bytes" % _ts())
        return

    t = _ts()
    # Full 3-frame
    if (
        total >= 35
        and checksum_ok(raw[:8])
        and checksum_ok(raw[8:16])
        and checksum_ok(raw[16:35])
        and raw[4] == 0xC5
        and raw[12] == 0x42
    ):
        f1, f2, f3 = raw[:8], raw[8:16], raw[16:35]
        decoded_lines, _ = decoded_fields_from_frames(f1, f2, f3)
        for line in decoded_lines:
            print("[%s] Decoded: %s" % (_ts(), line))
        opaque = 13  # F3 bytes we don't yet interpret (timers, etc.)
        print("[%s] Opaque: %d of %d bytes" % (_ts(), opaque, total))
        return

    # Single frame
    f1, f2, f3 = None, None, None
    if total == 8 and checksum_ok(raw):
        if raw[4] == 0xC5:
            f1 = raw
        elif raw[4] == 0x42:
            f2 = raw
    elif total == 19 and checksum_ok(raw):
        f3 = raw

    if f1 or f2 or f3:
        decoded_lines, _ = decoded_fields_from_frames(f1, f2, f3)
        for line in decoded_lines:
            print("[%s] Decoded: %s" % (_ts(), line))
        print("[%s] Opaque: 0 of %d bytes" % (_ts(), total))
        return

    # Partial or failure: we have bytes but no valid frame
    print("[%s] Decoded: (none — len=%d, checksum or id mismatch)" % (_ts(), total))
    print("[%s] Opaque: %d of %d bytes" % (_ts(), total, total))


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


def decoded_fields_from_frames(
    f1: Optional[Sequence[int]],
    f2: Optional[Sequence[int]],
    f3: Optional[Sequence[int]],
) -> Tuple[List[str], int]:
    """Build list of decoded field strings and count of bytes we do not yet interpret. Returns (decoded_lines, opaque_byte_count)."""
    lines: List[str] = []
    decoded_bytes = 0
    if f1 is not None and len(f1) >= 8:
        decoded_bytes += 8
        comfort = "comfort on" if len(f1) > 6 and (f1[6] & 0x10) else "comfort off"
        lines.append("F1: %s" % comfort)
    if f2 is not None and len(f2) >= 8:
        decoded_bytes += 8
        lines.append("F2: (fixed)")
    if f3 is not None and len(f3) >= 19:
        decoded_bytes += 19
        b5 = f3[5]
        mode_nib = (b5 >> 4) & 0x0F
        power = "ON" if (b5 & 0x01) else "OFF"
        mode = {"0": "AUTO", "2": "DRY", "3": "COOL", "4": "HEAT", "6": "FAN"}.get(
            str(mode_nib), "0x%x" % mode_nib
        )
        temp_c = f3[6] // 2 if 10 <= f3[6] // 2 <= 30 else None
        fan_byte = f3[8]
        fan_nib = (fan_byte >> 4) & 0x0F
        swing = "swing" if (fan_byte & 0x0F) == 0x0F else "no swing"
        fan = (
            "fan%d" % fan_nib
            if 3 <= fan_nib <= 7
            else (
                "Auto"
                if fan_nib == 0xA
                else "Silent" if fan_nib == 0xB else "0x%x" % fan_nib
            )
        )
        powerful = (f3[0x0D] & 0x01) != 0 if len(f3) > 0x0D else False
        econo = (f3[0x10] & 0x0F) == 0x04 if len(f3) > 0x10 else False
        parts = ["power=%s" % power, "mode=%s" % mode]
        if temp_c is not None:
            parts.append("temp=%dC" % temp_c)
        parts.extend(
            ["fan=%s" % fan, swing, "powerful=%s" % powerful, "econo=%s" % econo]
        )
        lines.append("F3: " + " ".join(parts))
    total = (8 if f1 else 0) + (8 if f2 else 0) + (19 if f3 else 0)
    opaque = max(0, total - decoded_bytes)
    return lines, opaque


def interpret_frames(
    f1: Optional[Sequence[int]],
    f2: Optional[Sequence[int]],
    f3: Optional[Sequence[int]],
) -> None:
    """Print human-readable frame summary (used by run_from_stdin)."""
    decoded_lines, _ = decoded_fields_from_frames(f1, f2, f3)
    for line in decoded_lines:
        if line.startswith("F3: "):
            print("  Frame3:" + line[3:])
        else:
            print("  ", line)


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
                sys.stderr.write(
                    "[daikin-recv] gap > %.1fs, reset and skip line\n" % GAP_LINE_SEC
                )
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
            sys.stderr.write(
                "[daikin-recv] line len=%d -> %d pairs\n" % (len(line), npairs)
            )
            sys.stderr.flush()

    flush_current()


def _consumer(
    unit_iter: Iterator[List[str]], unit_queue: queue.Queue[List[str]]
) -> None:
    """Run in thread: push each unit from the split-by-pause generator into the queue."""
    try:
        for unit in unit_iter:
            unit_queue.put(unit)
    except Exception:
        pass


def run_subprocess() -> None:
    """Thread consumes split-by-pause into a queue. After description, assert queue empty (drain and complain if not);
    then block 10s for one unit; parse or complain timeout. Ctrl-C exits."""
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

    unit_queue: queue.Queue[List[str]] = queue.Queue()
    unit_iter = read_units_by_pause(proc.stdout)
    consumer = threading.Thread(
        target=_consumer, args=(unit_iter, unit_queue), daemon=True
    )
    consumer.start()
    last_desc: Optional[str] = None
    capture_path = _capture_path_for_date()
    session: List[Any] = []  # One new file per run; only this session's units go in
    if DEBUG_RECV:
        sys.stderr.write(
            "[%s] [daikin-recv] subprocess started; consumer thread feeding queue; capture %s\n"
            % (_ts(), capture_path)
        )
        sys.stderr.flush()
    try:
        while True:
            try:
                sys.stdout.write("Description (Enter=reuse, empty=exit): ")
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
            # Assert queue empty after user pressed Enter (no data while typing).
            unexpected: List[List[str]] = []
            while True:
                try:
                    unexpected.append(unit_queue.get_nowait())
                except queue.Empty:
                    break
            if unexpected:
                sys.stderr.write(
                    "[%s] [daikin-recv] unexpected data (received while typing?); clearing and summarizing:\n"
                    % _ts()
                )
                sys.stderr.flush()
                for u in unexpected:
                    record = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "label": "unexpected",
                        "description": "(unexpected)",
                        "raw_lines": u,
                    }
                    _append_and_save_capture(capture_path, session, record)
                    parse_unit(u, "(unexpected)")
            # Block up to RECV_TIMEOUT_SEC for one unit.
            try:
                unit = unit_queue.get(timeout=RECV_TIMEOUT_SEC)
            except queue.Empty:
                sys.stderr.write(
                    "[%s] [daikin-recv] nothing received (timeout %.0fs); press remote after Enter.\n"
                    % (_ts(), RECV_TIMEOUT_SEC)
                )
                sys.stderr.flush()
                continue
            if DEBUG_RECV:
                lens = ", ".join(str(len(l)) for l in unit)
                sys.stderr.write(
                    "[%s] [daikin-recv] unit: %d lines (len %s)\n"
                    % (_ts(), len(unit), lens)
                )
                sys.stderr.flush()
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "label": "expected",
                "description": desc,
                "raw_lines": unit,
            }
            _append_and_save_capture(capture_path, session, record)
            parse_unit(unit, desc)
    except KeyboardInterrupt:
        pass
    finally:
        if DEBUG_RECV:
            sys.stderr.write("[%s] [daikin-recv] exiting\n" % _ts())
            sys.stderr.flush()
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        run_from_stdin()
    else:
        print("Listening on", LIRC_RX, "(Ctrl+C to stop)...")
        run_subprocess()
