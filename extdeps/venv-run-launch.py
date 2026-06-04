#!/usr/bin/env python3
"""
Run the target script under this interpreter (the venv Python).

Invoked only by ``venv-run.py`` as ``python venv-run-launch.py SCRIPT [ARGS...]``.
Catches ``ModuleNotFoundError`` so we can point at ``setup-venv.sh`` instead of
only a traceback (same remedy as when no venv exists: sync the environment).
"""

from __future__ import annotations

import os
import runpy
import sys
from typing import Optional


def _nearest_setup_venv(start_dir: str) -> Optional[str]:
    names = ("setup-venv.sh", "setup-venv")
    d = os.path.abspath(start_dir)
    while True:
        for name in names:
            cand = os.path.join(d, name)
            if not os.path.isfile(cand):
                continue
            if name == "setup-venv" and not os.access(cand, os.X_OK):
                continue
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _print_missing_module_help(script: str, exc: ModuleNotFoundError) -> None:
    script_dir = os.path.dirname(os.path.abspath(script))
    setup = (os.environ.get("VENV_RUN_SETUP_VENV_SH") or "").strip() or None
    if not setup:
        setup = _nearest_setup_venv(script_dir)

    lines = [
        "",
        "venv-run: this script needs a Python module that is not installed "
        "in the active virtualenv:",
        f"  {exc}",
        "",
    ]
    if setup:
        lines.extend(
            [
                "Install missing packages by running your project setup helper:",
                f"  {setup}",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "No setup-venv.sh was found walking up from the script directory.",
                "Install dependencies into this venv (for example "
                "`python -m pip install -r requirements.txt`).",
                "",
            ]
        )
    print("\n".join(lines), file=sys.stderr, end="")


def main() -> int:
    if len(sys.argv) < 2:
        print("venv-run-launch: internal error: missing SCRIPT", file=sys.stderr)
        return 2
    # Match ``python /path/to/script.py``: script directory must head sys.path.
    # ``runpy.run_path`` does not do this for a normal .py file (see stdlib
    # ``run_path``: the ``get_importer(...) is None`` branch).
    script = os.path.realpath(sys.argv[1])
    script_dir = os.path.dirname(script)
    sys.argv = [script] + sys.argv[2:]
    sys.path.insert(0, script_dir)
    try:
        runpy.run_path(script, run_name="__main__")
    except ModuleNotFoundError as exc:
        _print_missing_module_help(script, exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
