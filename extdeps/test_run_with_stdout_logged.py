"""Tests for run-with-stdout-logged supervision."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

RUNNER = Path(__file__).resolve().parent / "run-with-stdout-logged.py"


def _run_supervised(
    tmp_path: Path,
    runfile: Path,
    child: list[str],
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    logpath = tmp_path / "test.log"
    env = {
        **os.environ,
        "RUN_WITH_STDOUT_RUNFILE": str(runfile),
        "RUN_WITH_STDOUT_RESTART_SECS": "0",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(logpath),
            "0",
            "0",
            *child,
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_single_run_without_runfile(tmp_path: Path) -> None:
    logpath = tmp_path / "once.log"
    proc = subprocess.run(
        [
            sys.executable,
            str(RUNNER),
            str(logpath),
            "0",
            "0",
            sys.executable,
            "-c",
            "print('hello')",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0
    text = logpath.read_text(encoding="utf-8")
    assert "hello" in text
    assert "relaunch" not in text


def test_supervised_restarts_while_runfile_exists(tmp_path: Path) -> None:
    runfile = tmp_path / "dmz.run"
    runfile.touch()
    counter = tmp_path / "count.txt"
    counter.write_text("0", encoding="utf-8")
    script = tmp_path / "tick.sh"
    script.write_text(
        "#!/bin/sh\n"
        f'c=$(cat "{counter}")\n'
        'echo "tick=$c"\n'
        f'echo $((c + 1)) > "{counter}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    script.chmod(0o755)

    proc = subprocess.Popen(
        [
            sys.executable,
            str(RUNNER),
            str(tmp_path / "loop.log"),
            "0",
            "0",
            str(script),
        ],
        env={
            **os.environ,
            "RUN_WITH_STDOUT_RUNFILE": str(runfile),
            "RUN_WITH_STDOUT_RESTART_SECS": "0",
        },
    )
    logpath = tmp_path / "loop.log"
    try:
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            if logpath.is_file() and "relaunch iteration=2" in logpath.read_text(
                encoding="utf-8"
            ):
                runfile.unlink()
                break
            time.sleep(0.02)
        else:
            pytest.fail("supervisor did not reach iteration 2 before timeout")
        proc.wait(timeout=8)
        assert proc.returncode == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=3)

    log = logpath.read_text(encoding="utf-8")
    assert "relaunch iteration=2" in log
    assert "supervised_exit" in log


def test_supervised_exits_when_runfile_missing_at_start(tmp_path: Path) -> None:
    runfile = tmp_path / "gone.run"
    proc = _run_supervised(
        tmp_path,
        runfile,
        [sys.executable, "-c", "print('never')"],
    )
    assert proc.returncode == 0
    log = (tmp_path / "test.log").read_text(encoding="utf-8")
    assert "supervised_exit runfile_missing" in log
    assert "never" not in log
