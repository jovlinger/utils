#!/usr/bin/env python3
"""Capture IR from the remote with descriptions; save session as pickle for later analysis.

Flow: 1) Enter description (what you will press). 2) Press remote. 3) Press Enter to stop.
4) Repeat. Empty description exits and saves. Ctrl-C flushes and closes the file.

Saves to scribble dir so you can push for analysis. Uses ir-ctl -d /dev/lirc1 --receive.
"""

from __future__ import annotations

import argparse
import os
import pickle
import re
import select
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, List

# LIRC RX device on Pi Zero 2W with ANAVI IR pHAT (GPIO 17).
LIRC_RX: str = "/dev/lirc1"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(SCRIPT_DIR, "captures")


def capture_path_for_date() -> str:
    """Path for today's capture file: scribble/captures/ir_capture_YYYY-MM-DD.pkl."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(CAPTURES_DIR, f"ir_capture_{date_str}.pkl")


def iter_ir_pairs(line: str) -> List[List[Any]]:
    """Parse one line into [(kind, us), ...]. Handles 'pulse N space N ...' or 'N N ...' (alternating)."""
    tokens = line.strip().split()
    out: List[List[Any]] = []
    i = 0
    next_kind = "pulse"
    while i < len(tokens):
        t = tokens[i]
        if (
            t.lower() in ("pulse", "space")
            and i + 1 < len(tokens)
            and tokens[i + 1].isdigit()
        ):
            out.append([t.lower(), int(tokens[i + 1])])
            i += 2
        elif t.isdigit():
            out.append([next_kind, int(t)])
            next_kind = "space" if next_kind == "pulse" else "pulse"
            i += 1
        else:
            i += 1
    return out


def capture_one_record(proc_stdout: Any, stdin_fd: int) -> List[List[Any]]:
    """Read from proc_stdout until stdin becomes readable (user pressed Enter). Returns raw_ir list."""
    raw_ir: List[List[Any]] = []

    while True:
        r, _, _ = select.select([stdin_fd, proc_stdout], [], [], 0.25)
        if stdin_fd in r:
            return raw_ir
        if proc_stdout in r:
            line = proc_stdout.readline()
            if not line:
                return raw_ir
            pairs = iter_ir_pairs(line)
            for kind, us in pairs:
                raw_ir.append([kind, us])
            if pairs:
                sys.stderr.write(f"\r  received {len(raw_ir)} pairs  ")
                sys.stderr.flush()


def load_session(out_path: str) -> List[dict]:
    """Load session list from pickle file; return [] if missing or invalid."""
    if not os.path.isfile(out_path):
        return []
    try:
        with open(out_path, "rb") as f:
            return pickle.load(f)
    except (pickle.PickleError, OSError):
        return []


def save_session(out_path: str, session: List[dict]) -> None:
    """Write full session to pickle file; flush and close. No-op if session is empty."""
    if not session:
        return
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out_path, "wb") as f:
        pickle.dump(session, f, protocol=pickle.HIGHEST_PROTOCOL)
        f.flush()
        os.fsync(f.fileno())
    sys.stderr.write(f"[ir_capture] saved {len(session)} record(s) to {out_path}\n")
    sys.stderr.flush()


def run_capture(out_path: str, lirc_rx: str) -> None:
    session: List[dict] = load_session(out_path)

    try:
        while True:
            try:
                sys.stdout.write("Description (empty to exit): ")
                sys.stdout.flush()
                desc = input().strip()
            except (KeyboardInterrupt, EOFError):
                break
            if not desc:
                break

            print("Press remote now; press Enter when done.")
            sys.stdout.flush()
            sys.stderr.write("[ir_capture] started ir-ctl --receive\n")
            sys.stderr.flush()
            proc = subprocess.Popen(
                ["ir-ctl", "-d", lirc_rx, "--receive"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            try:
                raw_ir = capture_one_record(proc.stdout, sys.stdin.fileno())
            except (KeyboardInterrupt, EOFError):
                raw_ir = []
            finally:
                sys.stderr.write(
                    f"\n[ir_capture] stopping (captured {len(raw_ir)} pairs)\n"
                )
                sys.stderr.flush()
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    try:
                        proc.wait()
                    except KeyboardInterrupt:
                        pass

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "label": "expected",
                "description": desc,
                "raw_ir": raw_ir,
            }
            session.append(record)
            print(f"  Captured {len(raw_ir)} pulse/space pairs.")
    except KeyboardInterrupt:
        sys.stderr.write("\n[ir_capture] Ctrl-C, flushing session to file\n")
        sys.stderr.flush()
    finally:
        save_session(out_path, session)
        if not session:
            print("No records to save.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Capture IR with descriptions; save session as pickle (scribble dir)."
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output pickle path (default: scribble/captures/ir_capture_YYYY-MM-DD.pkl)",
    )
    ap.add_argument(
        "-d",
        "--device",
        default=LIRC_RX,
        help=f"LIRC receive device (default: {LIRC_RX})",
    )
    args = ap.parse_args()
    out_path = args.output if args.output is not None else capture_path_for_date()

    try:
        run_capture(out_path, args.device)
    except KeyboardInterrupt:
        sys.stderr.write("Interrupted.\n")
        sys.stderr.flush()
        sys.exit(0)


if __name__ == "__main__":
    main()
