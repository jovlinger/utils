#!/usr/bin/env python3
"""
Exec a Python script under the nearest ancestor virtualenv.

Designed to be used as a shebang interpreter:

    #!/usr/bin/env venv-run

When the kernel runs a script with that shebang, it invokes
``venv-run SCRIPT [ARGS...]``. ``venv-run`` then:

1. Resolves SCRIPT through any symlinks (so PATH-level symlinks like
   ``bin/binlinks/bff`` pointing at ``bin/bff.py`` still find the "real"
   file).
2. Walks up from the real script's directory looking for a virtualenv
   directory (``.venv``, ``venv``, or ``env`` - first match wins per level).
3. Sets ``VIRTUAL_ENV`` + prepends ``<venv>/bin`` to ``PATH`` and exec's
   the venv's ``python`` on a tiny launcher (``venv-run-launch.py``) that
   runs the script via ``runpy`` and prints hints if a dependency is missing
   (``ModuleNotFoundError``). Both that case and a missing venv point at the
   nearest ``setup-venv.sh`` (or ``setup-venv``) found walking up from the
   script, same as this repo's ``setup-venv.sh`` helpers.

This replaces the older ``pylauncher.sh`` scheme. The key difference: the
``.py`` file is now self-contained (shebang declares its runtime), so
symlinks to it can live anywhere on disk and the venv is discovered from
the file's real location rather than the symlink's location.

There is no dependency on any pip-installed package; this runs under the
system ``python3``, so it can always start regardless of venv state.

Tests live in ``tests/test_venv_run.py``.
"""

from __future__ import annotations

import os
import sys
from typing import Iterable, List, Optional


#: Directories (relative to each ancestor) that we consider to be a venv.
#: First match per level wins; ``.venv`` is preferred because that's the
#: convention in this repo.
VENV_NAMES: tuple = (".venv", "venv", "env")

#: Filenames to look for when suggesting how to create/sync a venv (nearest
#: ancestor of the script wins, same walk as ``requirements.txt``).
SETUP_VENV_FILENAMES: tuple = ("setup-venv.sh", "setup-venv")

#: Same directory as this file (``venv-run.py``), after resolving symlinks so
#: a ``venv-run`` symlink on ``PATH`` still finds ``venv-run-launch.py``.
_RUN_DIR = os.path.dirname(os.path.realpath(__file__))
_LAUNCHER = os.path.join(_RUN_DIR, "venv-run-launch.py")


def resolve_script(path: str) -> str:
    """Return the real (symlink-resolved) absolute path of ``path``."""
    return os.path.realpath(path)


def find_venv(
    start_dir: str, names: Iterable[str] = VENV_NAMES
) -> Optional[str]:
    """Walk up from ``start_dir`` looking for ``<dir>/<name>/bin/python``.

    Returns the absolute venv directory (``<dir>/<name>``) or ``None`` if
    none is found before hitting the filesystem root.
    """
    d = os.path.abspath(start_dir)
    while True:
        for name in names:
            candidate = os.path.join(d, name)
            py = os.path.join(candidate, "bin", "python")
            if os.path.isfile(py) and os.access(py, os.X_OK):
                return candidate
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def find_nearest_requirements_txt(start_dir: str) -> Optional[str]:
    """Walk up from ``start_dir``; return the first ``requirements.txt`` path."""
    d = os.path.abspath(start_dir)
    while True:
        cand = os.path.join(d, "requirements.txt")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def find_nearest_setup_venv(start_dir: str) -> Optional[str]:
    """Walk up from ``start_dir``; return the first setup-venv helper path."""
    d = os.path.abspath(start_dir)
    while True:
        for name in SETUP_VENV_FILENAMES:
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


def build_env(venv: str) -> dict:
    """Return an ``os.environ``-shaped dict with the venv activated.

    Mimics the subset of ``.venv/bin/activate`` that actually matters for
    running a script: ``VIRTUAL_ENV`` set, ``<venv>/bin`` prepended to
    ``PATH``, ``PYTHONHOME`` cleared if present.
    """
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = venv
    env.pop("PYTHONHOME", None)
    bin_dir = os.path.join(venv, "bin")
    cur_path = env.get("PATH", "")
    env["PATH"] = bin_dir + (os.pathsep + cur_path if cur_path else "")
    return env


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print("usage: venv-run SCRIPT [ARGS...]", file=sys.stderr)
        return 2

    script = argv[1]
    rest = argv[2:]

    real = resolve_script(script)
    if not os.path.isfile(real):
        print(f"venv-run: not a file: {real}", file=sys.stderr)
        return 2

    script_dir = os.path.dirname(real)
    venv = find_venv(script_dir)
    if venv is None:
        setup = find_nearest_setup_venv(script_dir)
        print("", file=sys.stderr)
        print(
            "venv-run: no virtualenv (.venv, venv, or env) found walking up from:",
            file=sys.stderr,
        )
        print(f"  {real}", file=sys.stderr)
        print("", file=sys.stderr)
        if setup:
            print("Create or refresh the environment with:", file=sys.stderr)
            print(f"  {setup}", file=sys.stderr)
        else:
            print(
                "No setup-venv.sh was found walking up from the script directory.\n"
                "Create a .venv next to this project and install dependencies.",
                file=sys.stderr,
            )
        print("", file=sys.stderr)
        return 1

    python = os.path.join(venv, "bin", "python")
    if not os.path.isfile(_LAUNCHER):
        print(
            f"venv-run: missing launcher next to this file: {_LAUNCHER}",
            file=sys.stderr,
        )
        return 127

    env = build_env(venv)
    env["VENV_RUN_REQUIREMENTS_TXT"] = (
        find_nearest_requirements_txt(script_dir) or ""
    )
    env["VENV_RUN_SETUP_VENV_SH"] = find_nearest_setup_venv(script_dir) or ""
    # execvpe replaces this process; no return on success.
    os.execvpe(python, [python, _LAUNCHER, real, *rest], env)
    # Unreachable, but keeps type-checkers happy.
    return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv))
