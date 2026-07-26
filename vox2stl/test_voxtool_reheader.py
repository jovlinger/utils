#!/usr/bin/env python3
"""Tests for voxtool.py reheader."""

from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path

import check_vox
import voxtool

STRAIGHT = Path(__file__).resolve().parent / "testdata" / "straight.vox"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_reheader_is_noop_on_straight_fixture() -> None:
    original = STRAIGHT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "straight.vox"
        path.write_text(original, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                ["voxtool.py", "reheader", "-out", str(path), str(STRAIGHT)]
            )
        require(exit_code == 0, f"expected pass, got {exit_code}; {stderr.getvalue()}")
        require(path.read_text(encoding="utf-8") == original, "straight.vox should be unchanged")
        check_exit = voxtool.main(["voxtool.py", "check", str(path)])
        require(check_exit == 0, f"check should pass after noop reheader; {check_exit}")


def test_reheader_fixes_stale_height_rows() -> None:
    text = "\n".join(
        [
            "layer base (0, 3, 9)",
            "XXX",
            "XXX",
            "   ",
            "net alias TX = GPIO43",
            "",
            "layer trace (0, 3, 9)",
            "...",
            "...",
            "",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "stale-height.vox"
        path.write_text(text, encoding="utf-8")
        before = check_vox.read_layers(path)
        require(before["base"].height == 9, "fixture should declare stale height_rows")
        require(len(before["base"].rows) == 2, "meta/whitespace must not count as rows")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "reheader", str(path)])
        require(exit_code == 0, f"expected pass, got {exit_code}; {stderr.getvalue()}")
        after = check_vox.read_layers(path)
        for name, layer in after.items():
            require(
                layer.height == len(layer.rows),
                f"{name}: height_rows={layer.height} != len(rows)={len(layer.rows)}",
            )
        require(after["base"].height == 2, "reheader should set height_rows to data rows")


def test_reheader_fails_on_offset_width_mismatch() -> None:
    text = "\n".join(
        [
            "layer base (0, 5, 1)",
            "XXXXX",
            "",
            "layer trace (1, 5, 1)",
            ".....",
            "",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "mismatch.vox"
        path.write_text(text, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "reheader", str(path)])
        require(exit_code == 1, f"expected failure, got {exit_code}")
        require(
            "cross-layer geometry mismatch" in stderr.getvalue(),
            f"missing mismatch message in {stderr.getvalue()!r}",
        )
