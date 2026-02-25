#!/usr/bin/env python3
"""Low-level IR capture: preserve everything ir-ctl can report.

No interpretation: this script does not decode, parse, or infer protocol.
Logs are raw ir-ctl output only, so improved parsing (e.g. in daikin-recv
or heatpumpirctl) can be applied to existing logs without re-capturing.

Uses mode2 format (one event per line) so nothing is truncated. Optionally
enables carrier measurement and wideband (learning) mode. Logs ir-ctl
--features at the top of the capture file for hardware diagnostics.

Output: scribble/captures/ir_capture_<timestamp>.log (plain text, verbatim
ir-ctl output, no decoding or processing).

Usage:
  ./ir_capture.py                       # normal capture
  ./ir_capture.py -m                    # also measure carrier frequency
  ./ir_capture.py -w -m                 # wideband (learning, ~5cm range)
  ./ir_capture.py -t 200000             # 200ms idle timeout
  ./ir_capture.py --features-only       # just print hardware features
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import select
import time
from datetime import datetime, timezone
from typing import TextIO

LIRC_RX: str = "/dev/lirc1"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(SCRIPT_DIR, "captures")


def query_features(device: str) -> str:
    """Run ir-ctl --features and return the output (or error text)."""
    try:
        r = subprocess.run(
            ["ir-ctl", "-d", device, "--features"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (r.stdout + r.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return "ir-ctl --features failed: %s" % e


def open_log(path: str) -> TextIO:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    return open(path, "a")


def build_recv_cmd(
    device: str,
    measure_carrier: bool,
    wideband: bool,
    timeout_us: int | None,
) -> list[str]:
    cmd = ["ir-ctl", "-d", device, "--receive", "--mode2"]
    if measure_carrier:
        cmd.append("--measure-carrier")
    if wideband:
        cmd.append("--wideband")
    if timeout_us is not None:
        cmd.extend(["--timeout", str(timeout_us)])
    return cmd


def _drain_remaining(proc_stdout, log_file: TextIO, timeout: float = 0.5) -> int:
    """Read any remaining buffered output from ir-ctl after user presses Enter."""
    count = 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        r, _, _ = select.select([proc_stdout], [], [], 0.05)
        if not r:
            break
        line = proc_stdout.readline()
        if not line:
            break
        log_file.write(line)
        count += 1
    return count


def capture_one_record(proc_stdout, stdin_fd: int, log_file: TextIO) -> int:
    """Pipe ir-ctl stdout to log verbatim until user presses Enter, then drain remaining."""
    lines = 0
    while True:
        r, _, _ = select.select([stdin_fd, proc_stdout], [], [], 0.25)
        if stdin_fd in r:
            sys.stdin.readline()
            lines += _drain_remaining(proc_stdout, log_file)
            return lines
        if proc_stdout in r:
            line = proc_stdout.readline()
            if not line:
                return lines
            log_file.write(line)
            lines += 1
            if lines % 50 == 0:
                sys.stderr.write("\r  %d lines captured  " % lines)
                sys.stderr.flush()


def run_capture(args: argparse.Namespace) -> None:
    log_file = open_log(args.output)
    features = query_features(args.device)

    log_file.write("# ir_capture log — %s\n" % datetime.now(timezone.utc).isoformat())
    log_file.write("# device: %s\n" % args.device)
    cmd = build_recv_cmd(args.device, args.measure_carrier, args.wideband, args.timeout)
    log_file.write("# command: %s\n" % " ".join(cmd))
    log_file.write("#\n# --- features ---\n")
    for fline in features.splitlines():
        log_file.write("# %s\n" % fline)
    log_file.write("# --- end features ---\n\n")
    log_file.flush()

    sys.stderr.write("[ir_capture] logging to %s\n" % args.output)
    sys.stderr.write("[ir_capture] command: %s\n" % " ".join(cmd))
    sys.stderr.write("[ir_capture] features:\n%s\n\n" % features)
    sys.stderr.flush()

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
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            log_file.write(
                "# %s  description=%s\n"
                % (datetime.now(timezone.utc).isoformat(), desc)
            )
            log_file.flush()

            try:
                nlines = capture_one_record(proc.stdout, sys.stdin.fileno(), log_file)
            except (KeyboardInterrupt, EOFError):
                nlines = 0
            finally:
                proc.terminate()
                try:
                    stderr_tail = proc.stderr.read()
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    stderr_tail = ""
                    proc.wait()

                if stderr_tail and stderr_tail.strip():
                    log_file.write("# stderr: %s\n" % stderr_tail.strip())

                log_file.write("\n")
                log_file.flush()
                sys.stderr.write("\n")
                sys.stderr.flush()

            record_count += 1
            print("  Captured %d lines." % nlines)

    except KeyboardInterrupt:
        sys.stderr.write("\n[ir_capture] Ctrl-C\n")
        sys.stderr.flush()
    finally:
        log_file.close()
        print("Saved %d record(s) to %s" % (record_count, args.output))


def main() -> None:
    default_path = os.path.join(
        CAPTURES_DIR,
        "ir_capture_%s.log" % datetime.now().strftime("%Y-%m-%dT%H%M%S"),
    )
    ap = argparse.ArgumentParser(
        description="Low-level IR capture. Preserves verbatim ir-ctl mode2 output."
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
    ap.add_argument(
        "-m",
        "--measure-carrier",
        action="store_true",
        help="Report carrier frequency (may enable wideband on some hardware)",
    )
    ap.add_argument(
        "-w",
        "--wideband",
        action="store_true",
        help="Wideband/learning mode (~5cm range, higher precision)",
    )
    ap.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=None,
        metavar="US",
        help="Receiver idle timeout in microseconds (e.g. 200000 = 200ms)",
    )
    ap.add_argument(
        "--features-only",
        action="store_true",
        help="Print hardware features and exit",
    )
    args = ap.parse_args()

    if args.features_only:
        print(query_features(args.device))
        return

    try:
        run_capture(args)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
