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
Exit code is the child process exit code (single run), or 0 after a supervised
stop when RUN_WITH_STDOUT_RUNFILE is unset or the runfile was removed.

Optional supervision (env):
  RUN_WITH_STDOUT_RUNFILE=/path/to/file
    While this path exists, restart CMD after each exit. Remove the file and
    terminate the child (SIGTERM to its process group, then SIGKILL) for a
    clean shutdown without another restart. Typical path: /tmp/dmz.run on tmpfs.
  RUN_WITH_STDOUT_RESTART_SECS
    Seconds to sleep before restarting after a child exit (default 1). Set 0
    for immediate restart.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, TextIO


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
    try:
        logpath.rename(rotated)
    except OSError as exc:
        # rename() fails with EBUSY if logpath is a mount point (e.g. a file bind-mount).
        # Log the problem to stderr and skip rotation rather than propagating the
        # exception, which would unwind the read loop into proc.wait() and deadlock
        # the logger while the child's pipe buffer fills up.
        print(
            f"run-with-stdout-logged.py: rotation skipped ({exc}); "
            f"logpath={logpath} may be a mount point",
            file=sys.stderr,
            flush=True,
        )
        return
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


def runfile_enabled(runfile: Optional[Path]) -> bool:
    return runfile is not None


def should_keep_running(runfile: Optional[Path]) -> bool:
    if runfile is None:
        return False
    return runfile.exists()


def restart_delay_secs() -> float:
    raw = (os.environ.get("RUN_WITH_STDOUT_RESTART_SECS") or "1").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 1.0


def resolve_runfile() -> Optional[Path]:
    raw = (os.environ.get("RUN_WITH_STDOUT_RUNFILE") or "").strip()
    if not raw:
        return None
    return Path(raw)


def _log_line(f: TextIO, line: str) -> None:
    f.write(line)
    f.flush()


def _append_status(logpath: Path, message: str) -> None:
    try:
        with open(logpath, "a", encoding="utf-8", errors="replace") as tf:
            _log_line(tf, message)
    except OSError:
        pass


def _child_status_lines(child_rc: int) -> List[str]:
    lines = [f"__run-with-stdout-logged__: child_returncode={child_rc}\n"]
    if child_rc < 0:
        sig = -child_rc
        try:
            sig_name = signal.Signals(sig).name
        except ValueError:
            sig_name = "UNKNOWN"
        lines.append(
            f"__run-with-stdout-logged__: child_terminated_by_signal={sig}({sig_name})\n"
        )
    return lines


def terminate_child(proc: subprocess.Popen[str]) -> None:
    """Stop the supervised child and its process group."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except OSError:
        try:
            proc.terminate()
        except OSError:
            return
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            try:
                proc.kill()
            except OSError:
                return
        proc.wait()


def _maybe_rotate_log(
    f: TextIO,
    logpath: Path,
    filelimit: int,
    totallimit: int,
) -> TextIO:
    if filelimit > 0 and file_size(logpath) > filelimit:
        f.close()
        rotate_if_needed(logpath, filelimit, totallimit)
        return open(logpath, "a", encoding="utf-8", errors="replace")
    return f


def _stream_child_output(
    proc: subprocess.Popen[str],
    f: TextIO,
    logpath: Path,
    filelimit: int,
    totallimit: int,
    runfile: Optional[Path],
) -> bool:
    """
    Copy child stdout to the log until the child exits.

    Returns True if the runfile disappeared while the child was still running
    (caller should not restart).
    """
    assert proc.stdout is not None
    stdout_fd: int = proc.stdout.fileno()
    stop_requested = False
    while True:
        if runfile_enabled(runfile) and not should_keep_running(runfile):
            stop_requested = True
            terminate_child(proc)
            break
        ready, _, _ = select.select([stdout_fd], [], [], 0.5)
        if ready:
            line = proc.stdout.readline()
            if line == "":
                break
            _log_line(f, line)
            f = _maybe_rotate_log(f, logpath, filelimit, totallimit)
        elif proc.poll() is not None:
            # Drain any trailing bytes after exit.
            for line in proc.stdout:
                _log_line(f, line)
                f = _maybe_rotate_log(f, logpath, filelimit, totallimit)
            break
    f.close()
    proc.wait()
    return stop_requested


def run_child_once(
    logpath: Path,
    filelimit: int,
    totallimit: int,
    cmd: List[str],
    runfile: Optional[Path],
    iteration: int,
) -> tuple[int, bool]:
    """
    Run CMD once, logging merged stdout/stderr.

    Returns (child_returncode, stop_requested). stop_requested is True when the
    runfile was removed during the run (supervised shutdown).
    """
    with open(logpath, "a", encoding="utf-8", errors="replace") as f:
        header = f"__run-with-stdout-logged__: launching cmd={cmd}\n"
        if iteration > 1:
            header = (
                f"__run-with-stdout-logged__: relaunch iteration={iteration} cmd={cmd}\n"
            )
        _log_line(f, header)
        _log_line(f, f"__run-with-stdout-logged__: logpath={str(logpath)}\n")
        if runfile_enabled(runfile):
            _log_line(
                f,
                f"__run-with-stdout-logged__: runfile={runfile} present={should_keep_running(runfile)}\n",
            )
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        stop_requested = _stream_child_output(
            proc, f, logpath, filelimit, totallimit, runfile
        )
        child_rc = proc.returncode if proc.returncode is not None else 0

    if filelimit > 0 and file_size(logpath) > filelimit:
        rotate_if_needed(logpath, filelimit, totallimit)
    for line in _child_status_lines(child_rc):
        _append_status(logpath, line)
    if stop_requested:
        _append_status(
            logpath,
            "__run-with-stdout-logged__: supervised_stop runfile_removed=True\n",
        )
    return child_rc, stop_requested


def run(
    logpath: Path,
    filelimit: int,
    totallimit: int,
    cmd: List[str],
    runfile: Optional[Path],
) -> int:
    if not cmd:
        print(
            "run-with-stdout-logged.py: need LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]",
            file=sys.stderr,
        )
        return 2

    logpath = logpath.resolve()
    logpath.parent.mkdir(parents=True, exist_ok=True)

    if not runfile_enabled(runfile):
        child_rc, _ = run_child_once(logpath, filelimit, totallimit, cmd, None, 1)
        return child_rc

    if not should_keep_running(runfile):
        _append_status(
            logpath,
            f"__run-with-stdout-logged__: supervised_exit runfile_missing={runfile}\n",
        )
        return 0

    iteration = 0
    last_rc = 0
    while should_keep_running(runfile):
        iteration += 1
        last_rc, stop_requested = run_child_once(
            logpath, filelimit, totallimit, cmd, runfile, iteration
        )
        if stop_requested or not should_keep_running(runfile):
            _append_status(
                logpath,
                "__run-with-stdout-logged__: supervised_exit stop_requested=True\n",
            )
            return 0
        delay = restart_delay_secs()
        _append_status(
            logpath,
            f"__run-with-stdout-logged__: restarting in {delay}s child_returncode={last_rc}\n",
        )
        if delay > 0:
            # Sleep in slices so removing the runfile stops the loop promptly.
            end = time.monotonic() + delay
            while time.monotonic() < end:
                if not should_keep_running(runfile):
                    _append_status(
                        logpath,
                        "__run-with-stdout-logged__: supervised_exit runfile_removed_during_delay=True\n",
                    )
                    return 0
                time.sleep(min(0.25, end - time.monotonic()))

    _append_status(
        logpath,
        "__run-with-stdout-logged__: supervised_exit runfile_removed=True\n",
    )
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if len(argv) < 4:
        print(
            "run-with-stdout-logged.py: need LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]",
            file=sys.stderr,
        )
        return 2
    logpath = Path(argv[0])
    try:
        filelimit = int(argv[1])
        totallimit = int(argv[2])
    except ValueError:
        print(
            "run-with-stdout-logged.py: FILELIMIT and TOTALLIMIT must be integers",
            file=sys.stderr,
        )
        return 2
    cmd = argv[3:]
    return run(logpath, filelimit, totallimit, cmd, resolve_runfile())


if __name__ == "__main__":
    sys.exit(main())
