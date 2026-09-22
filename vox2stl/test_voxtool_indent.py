#!/usr/bin/env python3
"""Tests for voxtool.py indent."""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
from pathlib import Path

import voxtool

REPO_ROOT = Path(__file__).resolve().parents[1]
STRAIGHT = Path(__file__).resolve().parent / "testdata" / "straight.vox"
PICO_SIDE = REPO_ROOT / "thermo" / "onboard" / "hardware" / "pico2w" / "hat" / "pico-side.vox"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_indent_round_trip_straight_fixture() -> None:
    original = STRAIGHT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "straight.vox"
        path.write_text(original, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            plus = voxtool.main(
                ["voxtool.py", "indent", "--delta", "1", str(path)]
            )
            minus = voxtool.main(
                ["voxtool.py", "indent", "--delta", "-1", str(path)]
            )
            check_exit = voxtool.main(["voxtool.py", "check", str(path)])
        require(plus == 0, f"indent +1 failed: {stderr.getvalue()}")
        require(minus == 0, f"indent -1 failed: {stderr.getvalue()}")
        require(path.read_text(encoding="utf-8") == original, "round-trip changed bytes")
        require(check_exit == 0, f"check failed after round-trip: {check_exit}")


def test_indent_round_trip_pico_side_check_clean() -> None:
    require(PICO_SIDE.is_file(), f"missing fixture {PICO_SIDE}")
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "pico-side.vox"
        shutil.copyfile(PICO_SIDE, path)
        original = path.read_text(encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            plus = voxtool.main(
                ["voxtool.py", "indent", "--delta", "1", str(path)]
            )
            require(plus == 0, f"indent +1 failed: {stderr.getvalue()}")
            check_indented = voxtool.main(["voxtool.py", "check", str(path)])
            require(check_indented == 0, f"check failed after +1: {check_indented}")
            minus = voxtool.main(
                ["voxtool.py", "indent", "--delta", "-1", str(path)]
            )
            require(minus == 0, f"indent -1 failed: {stderr.getvalue()}")
            check_exit = voxtool.main(["voxtool.py", "check", str(path)])
        require(path.read_text(encoding="utf-8") == original, "pico-side round-trip changed bytes")
        require(check_exit == 0, f"check failed after round-trip: {check_exit}")


def test_indent_fails_when_label_no_longer_fits() -> None:
    text = "\n".join(
        [
            "layer base (2, 3, 1)",
            "GP XXX",
            "",
            "layer trace (2, 3, 1)",
            "GP ...",
            "",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "tight.vox"
        path.write_text(text, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                ["voxtool.py", "indent", "--delta", "-1", str(path)]
            )
        require(exit_code == 1, f"expected failure, got {exit_code}")
        require(
            "does not fit" in stderr.getvalue(),
            f"missing fit error in {stderr.getvalue()!r}",
        )
