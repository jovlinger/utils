#!/usr/bin/env python3
"""Thin CLI around heatpumpirctl: receive ir-ctl mode2, decode via ARC452A9, print State.

Prompts for description, listens for one unit per description, logs raw lines to
scribble/captures/daikin_recv_<timestamp>.log. All parsing is in heatpumpirctl.ARC452A9.
"""

from __future__ import annotations

import os
import re
import select
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Iterator, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "onboard"))
from heatpumpirctl import State
from heatpumpirctl import ARC452A9 as proto

LIRC_RX: str = "/dev/lirc1"

PAUSE_SEC: float = 0.5
READ_TIMEOUT_SEC: float = 1.0
LIRC_TIMEOUT_US: int = 200_000
DEBUG_RECV: bool = True

_SCRIBBLE_DIR = os.path.dirname(os.path.abspath(__file__))
_CAPTURES_DIR = os.path.join(_SCRIBBLE_DIR, "captures")


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _hex(data: Any) -> str:
    return " ".join("%02x" % b for b in data)


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
# Parse + print
# ---------------------------------------------------------------------------


def parse_and_print(ir_text: str, description: str = "") -> Optional[State]:
    """Parse ir-ctl text via heatpumpirctl and print last decoded state."""
    t = _ts()
    if description:
        print("[%s] Description: %s" % (t, description))

    f1_raw: Optional[List[int]] = None
    f3_raw: Optional[List[int]] = None
    for kind, raw in proto.iter_frames(ir_text):
        if kind == "f1":
            f1_raw = raw
        elif kind in ("f3", "f3~"):
            f3_raw = raw

    if f3_raw is None and f1_raw is None:
        print("[%s] (noise — no valid frames)" % t)
        return None

    state = proto.load(f3_raw, f1_raw) if f3_raw else State()
    if f1_raw is not None and state.raw_f1 is None:
        state.raw_f1 = f1_raw
    if f3_raw is not None and state.raw_f3 is None:
        state.raw_f3 = f3_raw
    state.raw_ir = ir_text

    parts = []
    if state.raw_f1:
        parts.append("F1[%s]" % _hex(state.raw_f1))
    if state.raw_f3:
        tag = "F3" if not state.truncated else "F3~(%d/19)" % len(state.raw_f3)
        parts.append("%s[%s]" % (tag, _hex(state.raw_f3)))
    print("[%s] %s" % (t, "  ".join(parts)))
    print("[%s] %s" % (_ts(), state.summary()))
    return state


# ---------------------------------------------------------------------------
# run_from_stdin (piped mode, used by test)
# ---------------------------------------------------------------------------


def run_from_stdin() -> None:
    """Read ir-ctl mode2 lines from stdin; on each gap decode segment and print 3-frame (F1+F2+F3)."""
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
        for kind, raw in proto.decode_segment(current):
            if kind == "f1":
                frame1 = raw
            elif kind == "f2":
                frame2 = raw
            elif kind in ("f3", "f3~"):
                frame3 = raw
                if frame1 is not None and frame2 is not None:
                    print("Daikin 3-frame:")
                    print("  F1:", " ".join(f"{b:02x}" for b in frame1))
                    print("  F2:", " ".join(f"{b:02x}" for b in frame2))
                    print("  F3:", " ".join(f"{b:02x}" for b in frame3))
                    print("  Frame3:", proto.load(frame3, frame1).summary())
                frame1 = frame2 = frame3 = None

    last_line_time = 0.0
    for line in sys.stdin:
        now = time.time()
        if last_line_time > 0 and (now - last_line_time) > 2.0:
            flush_current()
            current.clear()
            in_gap = True
            last_line_time = now
            continue
        last_line_time = now
        for kind, us in proto.iter_events(line):
            if kind == "pulse":
                if in_gap and 2500 <= us <= 4500:
                    current.clear()
                    in_gap = False
                last_pulse_us = us
                last_was_pulse = True
                continue
            if kind == "space":
                if us >= proto.GAP_MIN:
                    flush_current()
                    current.clear()
                    in_gap = True
                elif (
                    last_was_pulse
                    and proto.PULSE_MIN <= last_pulse_us <= proto.PULSE_MAX
                ):
                    current.append((last_pulse_us, us))
                    in_gap = False
                last_was_pulse = False

    flush_current()


# ---------------------------------------------------------------------------
# run_subprocess: simple for-loop, description prompt, Ctrl-C to exit
# ---------------------------------------------------------------------------


def run_subprocess() -> None:
    for cmd in (
        [
            "stdbuf",
            "-oL",
            "ir-ctl",
            "-d",
            LIRC_RX,
            "--receive",
            "--mode2",
            "--timeout",
            str(LIRC_TIMEOUT_US),
        ],
        [
            "ir-ctl",
            "-d",
            LIRC_RX,
            "--receive",
            "--mode2",
            "--timeout",
            str(LIRC_TIMEOUT_US),
        ],
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

            ir_text = "".join(unit)
            _log_unit(log_file, desc, unit)
            parse_and_print(ir_text, desc)
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
                    parse_and_print("".join(data_lines), desc)
                    data_lines = []
                m = re.search(r"description=(.+?)\s{2,}lines=", line)
                desc = m.group(1) if m else ""
            elif line.strip():
                data_lines.append(line)
        if data_lines:
            parse_and_print("".join(data_lines), desc)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        run_from_stdin()
    elif len(sys.argv) > 2 and sys.argv[1] == "--parse-log":
        run_from_log(sys.argv[2])
    else:
        print("Listening on", LIRC_RX, "(Ctrl+C to stop)...")
        run_subprocess()
