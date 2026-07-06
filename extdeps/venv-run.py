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
3. If none is found but a ``requirements.txt`` exists walking up, creates the
   venv automatically next to the nearest one (reusing an existing ``.venv``/
   ``venv``/``env`` marker directory's name when that directory is already
   there, since repos commit a marker-only ``.venv/README.md`` -- generated
   contents are gitignored -- specifically so a fresh checkout still knows
   where the venv belongs) and installs ``requirements.txt`` into it. A
   missing venv with no ``requirements.txt`` anywhere above still falls back
   to pointing at the nearest ``setup-venv.sh`` (or ``setup-venv``).
4. Sets ``VIRTUAL_ENV`` + prepends ``<venv>/bin`` to ``PATH`` and exec's
   the venv's ``python`` on a tiny launcher (``venv-run-launch.py``) that
   runs the script via ``runpy`` and prints hints if a dependency is missing
   (``ModuleNotFoundError``).

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
import subprocess
import sys
from typing import Iterable, List, Optional


#: Directories (relative to each ancestor) that we consider to be a venv.
#: First match per level wins; ``.venv`` is preferred because that's the
#: convention in this repo.
VENV_NAMES: tuple = (".venv", "venv", "env")

#: Marker committed in place of a venv's contents (see ``create_venv``): only
#: this file is meant to be tracked in git, so a fresh checkout still knows
#: where the venv belongs even though the generated contents are gitignored.
_MARKER_README = """\
# Project virtualenv marker

This directory marks where the project-local Python virtualenv belongs.
The launcher searches upward for the nearest .venv, venv, or env directory.

Only this README is meant to be committed; the generated virtualenv contents
stay local to the machine.
"""

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


def find_venv_creation_target(start_dir: str) -> Optional[str]:
    """Return where a new venv belongs, or ``None`` if there is nothing to create.

    Walks up for the nearest ``requirements.txt`` (same as
    ``find_nearest_requirements_txt``): its directory is "closest to the
    python program" being run, so that is where the venv goes. If that
    directory already has a ``.venv``/``venv``/``env`` marker (even a
    marker-only checkout with just a README - see the repo convention of not
    versioning generated venv contents), its existing name is reused instead
    of always defaulting to ``.venv``.
    """
    req = find_nearest_requirements_txt(start_dir)
    if req is None:
        return None
    req_dir = os.path.dirname(req)
    for name in VENV_NAMES:
        candidate = os.path.join(req_dir, name)
        if os.path.isdir(candidate):
            return candidate
    return os.path.join(req_dir, VENV_NAMES[0])


def create_venv(venv_dir: str, requirements_txt: str) -> bool:
    """Create ``venv_dir`` with the running interpreter and install requirements.

    Uses ``sys.executable`` (whatever ambient ``python3`` launched this
    process) the same way ``create_pipenv.sh``/``setup-venv.sh`` use
    whatever ``python3`` is on ``PATH``. Safe to call when ``venv_dir``
    already exists as a marker-only directory: ``python -m venv`` populates
    missing venv files alongside the existing README rather than erroring.
    Returns True on success; prints its own diagnostics on failure.
    """
    print(f"venv-run: no virtualenv found; creating one at {venv_dir}", file=sys.stderr)
    try:
        subprocess.run([sys.executable, "-m", "venv", venv_dir], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"venv-run: failed to create venv at {venv_dir}: {exc}", file=sys.stderr)
        return False
    readme = os.path.join(venv_dir, "README.md")
    if not os.path.isfile(readme):
        with open(readme, "w", encoding="utf-8") as fh:
            fh.write(_MARKER_README)
    python = os.path.join(venv_dir, "bin", "python")
    print(f"venv-run: installing {requirements_txt}", file=sys.stderr)
    try:
        subprocess.run([python, "-m", "pip", "install", "-r", requirements_txt, "-q"], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"venv-run: failed to install {requirements_txt}: {exc}", file=sys.stderr)
        return False
    return True


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
        target = find_venv_creation_target(script_dir)
        if target is not None:
            requirements_txt = find_nearest_requirements_txt(script_dir)
            assert requirements_txt is not None  # implied by find_venv_creation_target
            if create_venv(target, requirements_txt):
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
