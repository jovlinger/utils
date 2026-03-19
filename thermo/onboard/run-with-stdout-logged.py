#!/usr/bin/env python3
"""
Generic runner: run a command and append its stdout/stderr to a log file with
rotation and total size cap.

Usage:
  run-with-stdout-logged.py LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]
"""

from __future__ import annotations

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
    """Delete oldest rotated files until their total size <= totallimit."""
    if totallimit <= 0:
        return
    candidates = rotated_logs(logpath)
    total = sum(file_size(p) for p in candidates)
    if total <= totallimit:
        return
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


def run(logpath: Path, filelimit: int, totallimit: int, cmd: List[str]) -> int:
    if not cmd:
        print(
            "run-with-stdout-logged.py: need LOGPATH FILELIMIT TOTALLIMIT CMD [ARGS...]",
            file=sys.stderr,
        )
        return 2
    logpath = logpath.resolve()
    logpath.parent.mkdir(parents=True, exist_ok=True)
    with open(logpath, "a", encoding="utf-8", errors="replace") as f:
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
            f.close()
            if filelimit > 0 and file_size(logpath) > filelimit:
                rotate_if_needed(logpath, filelimit, totallimit)
    return proc.returncode if proc.returncode is not None else 0


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
    return run(logpath, filelimit, totallimit, cmd)


if __name__ == "__main__":
    sys.exit(main())
