#!/usr/bin/env python3
"""Fast test run for the todos CLI, hard-capped so a hung test cannot stall a caller.

Runs pytest over this directory. Extra argv passes through, so a targeted run is
``./run-tests.py test_todo_db.py -k redirect``. The cap is ``$TODO_TEST_TIMEOUT``
seconds (default 60); on expiry the whole process group is killed and the exit
code is 124, the same code ``timeout(1)`` uses.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

DEFAULT_TIMEOUT = 60.0
TIMEOUT_EXIT = 124


def _limit() -> float:
    raw = os.environ.get("TODO_TEST_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return float(raw)
    except ValueError:
        sys.exit(f"run-tests: TODO_TEST_TIMEOUT is not a number: {raw!r}")


def main(argv: list[str]) -> int:
    here = Path(__file__).resolve().parent
    limit = _limit()
    # Own process group: pytest shells out to git, so a timeout has to take the
    # children with it.
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", *(argv or ["-q"])],
        cwd=here,
        start_new_session=True,
    )
    try:
        return proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        print(f"run-tests: timed out after {limit:g}s", file=sys.stderr)
        return TIMEOUT_EXIT


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
