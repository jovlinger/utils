#!/usr/bin/env python3
"""Capture IR from the remote with descriptions; save session as JSON for later analysis.

Flow: 1) Enter description (what you will press). 2) Press remote. 3) Press Enter to stop.
4) Repeat. Empty description exits and saves the session.

Handles Ctrl-C cleanly: saves session and exits without traceback.
Uses ir-ctl -d /dev/lirc1 --receive (Pi Zero 2W + ANAVI IR pHAT).
"""

from __future__ import annotations

import argparse
import json
import re
import select
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

# LIRC RX device on Pi Zero 2W with ANAVI IR pHAT (GPIO 17).
LIRC_RX: str = "/dev/lirc1"


def parse_ir_line(line: str) -> Optional[Tuple[str, int]]:
    """Return ('pulse', us) or ('space', us) or None. Accepts 'pulse N', 'space N', or bare N (mode2)."""
    line = line.strip()
    if not line:
        return None
    m = re.match(r"(pulse|space)\s+(\d+)", line, re.I)
    if m:
        return m.group(1).lower(), int(m.group(2))
    if line.isdigit():
        return ("_mode2_", int(line))
    return None


def capture_one_record(proc_stdout: Any, stdin_fd: int) -> List[List[Any]]:
    """Read from proc_stdout until stdin becomes readable (user pressed Enter). Returns raw_ir list."""
    raw_ir: List[List[Any]] = []
    next_kind = "pulse"  # for mode2 (bare number) lines

    while True:
        r, _, _ = select.select([stdin_fd, proc_stdout], [], [], 0.25)
        if stdin_fd in r:
            return raw_ir
        if proc_stdout in r:
            line = proc_stdout.readline()
            if not line:
                return raw_ir
            parsed = parse_ir_line(line)
            if parsed:
                kind, us = parsed
                if kind == "_mode2_":
                    kind = next_kind
                    next_kind = "space" if next_kind == "pulse" else "pulse"
                if kind in ("pulse", "space"):
                    raw_ir.append([kind, us])


def run_capture(out_path: str, lirc_rx: str) -> None:
    session: List[dict] = []

    while True:
        try:
            desc = input("Description (empty to exit): ").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if not desc:
            break

        print("Press remote now; press Enter when done.")
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
            "description": desc,
            "timestamp": datetime.now(timezone.utc()).isoformat(),
            "raw_ir": raw_ir,
        }
        session.append(record)
        print(f"  Captured {len(raw_ir)} pulse/space pairs.")

    if session:
        try:
            with open(out_path, "w") as f:
                json.dump({"records": session}, f, indent=2)
            print(f"Saved {len(session)} record(s) to {out_path}")
        except (KeyboardInterrupt, OSError) as e:
            print(f"Could not save: {e}", file=sys.stderr)
    else:
        print("No records to save.")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Capture IR with descriptions; save session as JSON."
    )
    ap.add_argument(
        "-o",
        "--output",
        default="ir_capture.json",
        help="Output JSON path (default: ir_capture.json)",
    )
    ap.add_argument(
        "-d",
        "--device",
        default=LIRC_RX,
        help=f"LIRC receive device (default: {LIRC_RX})",
    )
    args = ap.parse_args()

    try:
        run_capture(args.output, args.device)
    except KeyboardInterrupt:
        print(
            "\nInterrupted; session saved if any records were captured.",
            file=sys.stderr,
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
