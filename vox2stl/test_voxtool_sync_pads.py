#!/usr/bin/env python3
"""Tests for voxtool.py sync-pads."""

from __future__ import annotations

import contextlib
import io
import shutil
import tempfile
from pathlib import Path

import check_vox
import voxtool

REPO_ROOT = Path(__file__).resolve().parents[1]
PRINT_HEAD = REPO_ROOT / "thermo" / "onboard" / "hardware" / "print-head-clean.vox"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _design(layer: check_vox.Layer, row: str) -> str:
    return check_vox.design_window(layer, row)


def test_sync_pads_trace_to_base_on_print_head_clean() -> None:
    require(PRINT_HEAD.is_file(), f"missing fixture {PRINT_HEAD}")
    original = PRINT_HEAD.read_text(encoding="utf-8")
    # Clear base pads to X so sync-pads must restore them from trace.
    rewritten_lines: list[str] = []
    in_base = False
    for raw in original.splitlines(keepends=True):
        line, ending = voxtool.split_line_ending(raw)
        if line.startswith("layer base"):
            in_base = True
            rewritten_lines.append(raw)
            continue
        if line.startswith("layer "):
            in_base = False
        if in_base and line and not line.startswith("#"):
            cleared = "".join("X" if char in "*O" else char for char in line)
            rewritten_lines.append(cleared + ending)
        else:
            rewritten_lines.append(raw)
    stripped = "".join(rewritten_lines)

    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "print-head-clean.vox"
        path.write_text(stripped, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                [
                    "voxtool.py",
                    "sync-pads",
                    "--from=trace",
                    "--to=base",
                    str(path),
                ]
            )
        require(exit_code == 0, f"expected pass, got {exit_code}; {stderr.getvalue()}")
        layers = check_vox.read_layers(path)
        base = layers["base"]
        trace = layers["trace"]
        for base_row, trace_row in zip(base.rows, trace.rows):
            for base_char, trace_char in zip(
                _design(base, base_row), _design(trace, trace_row)
            ):
                if trace_char in check_vox.PAD_CHARS:
                    require(
                        base_char == trace_char,
                        f"base missing pad {trace_char!r}: {base_row!r} vs {trace_row!r}",
                    )
        check_exit = voxtool.main(["voxtool.py", "check", str(path)])
        require(check_exit == 0, f"check should pass after sync-pads; {check_exit}")


def test_sync_pads_base_to_trace_upsert() -> None:
    text = "\n".join(
        [
            "layer base (0, 3, 1)",
            "X*O",
            "",
            "layer trace (0, 3, 1)",
            "...",
            "",
        ]
    )
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "pads.vox"
        path.write_text(text, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                [
                    "voxtool.py",
                    "sync-pads",
                    "--from=base",
                    "--to=trace",
                    str(path),
                ]
            )
        require(exit_code == 0, f"expected pass, got {exit_code}; {stderr.getvalue()}")
        layers = check_vox.read_layers(path)
        # Upsert only: X is not a pad, so first cell stays '.'
        require(
            layers["trace"].rows[0] == ".*O",
            f"expected '.*O', got {layers['trace'].rows[0]!r}",
        )
        check_exit = voxtool.main(["voxtool.py", "check", str(path)])
        require(check_exit == 0, f"check should pass; {check_exit}")


def test_sync_pads_is_noop_when_already_aligned() -> None:
    require(PRINT_HEAD.is_file(), f"missing fixture {PRINT_HEAD}")
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "print-head-clean.vox"
        shutil.copyfile(PRINT_HEAD, path)
        before = path.read_text(encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                [
                    "voxtool.py",
                    "sync-pads",
                    "--from=trace",
                    "--to=base",
                    str(path),
                ]
            )
        require(exit_code == 0, f"expected pass, got {exit_code}; {stderr.getvalue()}")
        require(path.read_text(encoding="utf-8") == before, "already-aligned file changed")
