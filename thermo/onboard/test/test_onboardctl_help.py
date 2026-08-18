"""Smoke tests for onboardctl scaffold."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ONBOARDCTL = Path(__file__).resolve().parents[1] / "onboardctl" / "onboardctl.py"


def test_help_lists_subcommands() -> None:
    completed = subprocess.run(
        [sys.executable, str(ONBOARDCTL), "help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "onboardctl subcommands:" in completed.stdout
    assert "help" in completed.stdout
    assert "healthz" in completed.stdout
