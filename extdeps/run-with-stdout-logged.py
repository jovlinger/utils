#!/usr/bin/env python3
"""
Generic runner: run a command and append its stdout/stderr to a log file with
rotation and total size cap.

Usage:
  run-with-stdout-logged.py LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]

LOGPATH:   Path to the log file (created or appended to).
FILELIMIT: When the current log file exceeds this many bytes, it is renamed to
           LOGPATH.<isodatetime> and a new empty LOGPATH is used.
TOTALLIMIT: After we rotate, if total size of all LOGPATH.<timestamp>
            files exceeds this, oldest rotated files are deleted until total <= TOTALLIMIT.
CMD [ARGS]: Command to run; its stdout and stderr are merged and appended to
            the log line by line.

If LOGPATH already exists at startup, it is kept and we append to it.
Exit code is the child process exit code.
"""

from __future__ import annotations

import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


def isodatetime_suffix() -> str:
    """Filesystem-safe ISO datetime suffix (no colons)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S") + "Z"


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def rotate_if_needed(logpath: Path, filelimit: int, totallimit: int) -> None:
    if filelimit <= 0 or file_size(logpath) <= filelimit:
        return
    suffix = isodatetime_suffix()
    rotated = Path(str(logpath) + "." + suffix)
    logpath.rename(rotated)
    logpath.touch()
    prune_until_total_at_most(logpath, totallimit)


def rotated_logs(logpath: Path) -> List[Path]:
    """All rotated files (logpath.<suffix>) in same directory, any suffix."""
    base = logpath.name + "."
    parent = logpath.parent
    out: List[Path] = []
    try:
        for p in parent.iterdir():
            if p.name.startswith(base) and p.is_file():
                out.append(p)
    except OSError:
        pass
    return out


def prune_until_total_at_most(logpath: Path, totallimit: int) -> None:
    """Delete oldest LOGPATH.<timestamp> files until their total size <= totallimit."""
    if totallimit <= 0:
        return
    candidates = rotated_logs(logpath)
    total = sum(file_size(p) for p in candidates)
    if total <= totallimit:
        return
    # Sort by mtime ascending (oldest first)
    candidates.sort(key=lambda p: p.stat().st_mtime)
    for p in candidates:
        if total <= totallimit:
            break
        try:
            s = p.stat().st_size
            p.unlink()
            total -= s
        except OSError:
            pass


def run(
    logpath: Path,
    filelimit: int,
    totallimit: int,
    cmd: List[str],
) -> int:
    if not cmd:
        print("run-with-stdout-logged.py: need LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]", file=sys.stderr)
        return 2

    logpath = logpath.resolve()
    logpath.parent.mkdir(parents=True, exist_ok=True)
    # Keep existing log; append from start
    with open(logpath, "a", encoding="utf-8", errors="replace") as f:
        # Header: even if the child dies by SIGILL with no output, we still have
        # the exact command that was being executed.
        f.write(f"__run-with-stdout-logged__: launching cmd={cmd}\n")
        f.write(f"__run-with-stdout-logged__: logpath={str(logpath)}\n")
        f.flush()
        proc: Optional[subprocess.Popen[str]] = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                f.write(line)
                f.flush()
                if filelimit > 0 and file_size(logpath) > filelimit:
                    f.close()
                    rotate_if_needed(logpath, filelimit, totallimit)
                    f = open(logpath, "a", encoding="utf-8", errors="replace")
        finally:
            proc.wait()
            child_rc = proc.returncode if proc.returncode is not None else 0
            # Final rotation (prune runs inside rotate_if_needed)
            f.close()
            if filelimit > 0 and file_size(logpath) > filelimit:
                rotate_if_needed(logpath, filelimit, totallimit)
            # Always append a final status line (useful when the child dies by signal
            # like SIGILL and prints nothing further).
            try:
                with open(logpath, "a", encoding="utf-8", errors="replace") as tf:
                    tf.write(f"__run-with-stdout-logged__: child_returncode={child_rc}\n")
                    if child_rc < 0:
                        sig = -child_rc
                        try:
                            sig_name = signal.Signals(sig).name
                        except ValueError:
                            sig_name = "UNKNOWN"
                        tf.write(
                            f"__run-with-stdout-logged__: child_terminated_by_signal={sig}({sig_name})\n"
                        )
                    tf.flush()
            except OSError:
                # Best-effort: if we cannot write the status line, the captured stdout/stderr
                # is still useful.
                pass

    return proc.returncode if proc.returncode is not None else 0


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) < 4:
        print("run-with-stdout-logged.py: need LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]", file=sys.stderr)
        return 2
    logpath = Path(argv[0])
    try:
        filelimit = int(argv[1])
        totallimit = int(argv[2])
    except ValueError:
        print("run-with-stdout-logged.py: FILELIMIT and TOTALLIMIT must be integers", file=sys.stderr)
        return 2
    cmd = argv[3:]
    return run(logpath, filelimit, totallimit, cmd)


if __name__ == "__main__":
    sys.exit(main())
