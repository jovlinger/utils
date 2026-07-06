"""Tests for the help subcommand and --help alias."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SHADUP_PY), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_help_subcommand_shows_top_level_usage() -> None:
    result = _run(["help"])
    assert "usage: shadup" in result.stdout
    assert "help" in result.stdout
    assert "store" in result.stdout


def test_help_alias_shows_top_level_usage() -> None:
    result = _run(["--help"])
    assert result.stdout == _run(["help"]).stdout


def test_help_with_action_shows_action_usage() -> None:
    result = _run(["help", "extract"])
    assert "usage: shadup extract" in result.stdout
    assert "hardlink when the target is on the same filesystem as shadir" in result.stdout


def test_help_alias_with_action_shows_action_usage() -> None:
    result = _run(["--help", "extract"])
    assert result.stdout == _run(["help", "extract"]).stdout


def test_action_help_still_works() -> None:
    result = _run(["extract", "--help"])
    assert "usage: shadup extract" in result.stdout
