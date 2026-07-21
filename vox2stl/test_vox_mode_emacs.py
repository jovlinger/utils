#!/usr/bin/env python3
"""Emacs batch smoke and mirror parity for vox-mode."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

import voxtool

VOX2STL = Path(__file__).resolve().parent
REPO_ROOT = VOX2STL.parent
EMACS_DIR = VOX2STL / "emacs"
STRAIGHT = VOX2STL / "testdata" / "straight.vox"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def find_emacs() -> str:
    candidates: List[str] = []
    env = os.environ.get("EMACS")
    if env:
        candidates.append(env)
    candidates.extend(
        [
            "/Applications/Emacs.app/Contents/MacOS/Emacs",
            "/Applications/Emacs.app/Contents/MacOS/Emacs-arm64-11",
            "/Applications/Emacs.app/Contents/MacOS/emacs",
            "/opt/homebrew/bin/emacs",
            "/usr/local/bin/emacs",
        ]
    )
    which = shutil.which("emacs")
    if which:
        candidates.append(which)
    for path in candidates:
        if path and Path(path).is_file() and os.access(path, os.X_OK):
            try:
                subprocess.run(
                    [path, "--batch", "--eval", "(kill-emacs 0)"],
                    check=True,
                    capture_output=True,
                    timeout=30,
                )
                return path
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                continue
    raise AssertionError(
        "no working Emacs binary found; set EMACS to a runnable emacs for E1 gates"
    )


def test_emacs_batch_vox_mode_check() -> None:
    emacs = find_emacs()
    cmd = [
        emacs,
        "--batch",
        "-L",
        str(EMACS_DIR),
        "-l",
        "vox-mode.el",
        "--eval",
        (
            f'(progn (find-file "{STRAIGHT}") (vox-mode) (vox-mode-check)'
            f" (kill-emacs 0))"
        ),
    ]
    completed = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    require(
        completed.returncode == 0,
        f"emacs batch check failed ({completed.returncode}): "
        f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
    )


def test_emacs_mirror_parity_with_voxtool() -> None:
    emacs = find_emacs()
    original = STRAIGHT.read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp_dir:
        mode_path = Path(tmp_dir) / "mode-mirrored.vox"
        tool_path = Path(tmp_dir) / "tool-mirrored.vox"
        mode_path.write_text(original, encoding="utf-8")
        tool_path.write_text(original, encoding="utf-8")

        tool_exit = voxtool.main(["voxtool.py", "mirror", str(tool_path)])
        require(tool_exit == 0, f"voxtool mirror failed: {tool_exit}")

        cmd = [
            emacs,
            "--batch",
            "-L",
            str(EMACS_DIR),
            "-l",
            "vox-mode.el",
            "--eval",
            (
                f'(progn (find-file "{mode_path}") (vox-mode) (vox-mode-mirror)'
                f" (kill-emacs 0))"
            ),
        ]
        completed = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
        require(
            completed.returncode == 0,
            f"emacs mirror failed ({completed.returncode}): "
            f"stdout={completed.stdout!r} stderr={completed.stderr!r}",
        )
        mode_bytes = mode_path.read_text(encoding="utf-8")
        tool_bytes = tool_path.read_text(encoding="utf-8")
        require(
            mode_bytes == tool_bytes,
            "emacs vox-mode-mirror and voxtool.py mirror differ",
        )
        require(mode_bytes != original, "mirror left file unchanged")
