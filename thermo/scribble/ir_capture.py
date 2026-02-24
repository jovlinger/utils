#!/usr/bin/env python3
"""Capture raw IR from the remote with descriptions; save as plain text log.

Flow: 1) Enter description. 2) Press remote. 3) Press Enter to stop capture.
4) Repeat. Empty description exits. Ctrl-C saves and exits.

Output: scribble/captures/ir_capture_<timestamp>.log (plain text, one section
per capture, raw ir-ctl lines verbatim).
"""

from __future__ import annotations

import argparse
import os
import select
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

LIRC_RX: str = "/dev/lirc1"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(SCRIPT_DIR, "captures")


def open_capture_log(out_path: str) -> TextIO:
    d = os.path.dirname(out_path)
    if d:
        os.makedirs(d, exist_ok=True)
    f = open(out_path, "a")
    sys.stderr.write("[ir_capture] logging to %s\n" % out_path)
    sys.stderr.flush()
    return f


def capture_one_record(proc_stdout: Any, stdin_fd: int, log_file: TextIO) -> int:
    """Read from proc_stdout until stdin becomes readable (user pressed Enter). Returns pair count."""
    pair_count = 0
    while True:
        r, _, _ = select.select([stdin_fd, proc_stdout], [], [], 0.25)
        if stdin_fd in r:
            return pair_count
        if proc_stdout in r:
            line = proc_stdout.readline()
            if not line:
                return pair_count
            log_file.write(line)
            pair_count += line.count("pulse") + line.count("space")
            if pair_count > 0:
                sys.stderr.write("\r  received ~%d values  " % pair_count)
                sys.stderr.flush()


def run_capture(out_path: str, lirc_rx: str) -> None:
    log_file = open_capture_log(out_path)
    record_count = 0
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
            proc = subprocess.Popen(
                ["ir-ctl", "-d", lirc_rx, "--receive"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            log_file.write(
                "# %s  description=%s\n"
                % (datetime.now(timezone.utc).isoformat(), desc)
            )
            log_file.flush()
            try:
                pair_count = capture_one_record(
                    proc.stdout, sys.stdin.fileno(), log_file
                )
            except (KeyboardInterrupt, EOFError):
                pair_count = 0
            finally:
                log_file.write("\n")
                log_file.flush()
                sys.stderr.write("\n")
                sys.stderr.flush()
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            record_count += 1
            print("  Captured ~%d values." % pair_count)
    except KeyboardInterrupt:
        sys.stderr.write("\n[ir_capture] Ctrl-C\n")
        sys.stderr.flush()
    finally:
        log_file.close()
        print("Saved %d record(s) to %s" % (record_count, out_path))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Capture raw IR with descriptions; save as plain text log."
    )
    default_path = os.path.join(
        CAPTURES_DIR,
        "ir_capture_%s.log" % datetime.now().strftime("%Y-%m-%dT%H%M%S"),
    )
    ap.add_argument(
        "-o",
        "--output",
        default=default_path,
        help="Output log path (default: captures/ir_capture_<timestamp>.log)",
    )
    ap.add_argument(
        "-d",
        "--device",
        default=LIRC_RX,
        help="LIRC receive device (default: %s)" % LIRC_RX,
    )
    args = ap.parse_args()

    try:
        run_capture(args.output, args.device)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
