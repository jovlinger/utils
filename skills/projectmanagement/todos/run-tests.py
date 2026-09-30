#!/usr/bin/env python3
"""Timeboxed pytest driver for the todos CLI, selectable by tier and by surface.

Plain ``./run-tests.py`` is the fast suite: every test except the ``e2e`` tier,
which is the only tier that starts a fresh CLI and a fresh store per test.
``--all`` adds those back. Tiers and what belongs in each are defined in
``tiering.py``.

  ./run-tests.py                     fast: unit + integration, all surfaces
  ./run-tests.py --all               everything, including e2e
  ./run-tests.py --tier e2e          one tier
  ./run-tests.py --surface web       one surface (see --list)
  ./run-tests.py --surface store -k redirect -vv   unknown args go to pytest

The run is capped at ``$TODO_TEST_TIMEOUT`` seconds, defaulting to 60 when no
e2e test is selected and 900 when one is. On expiry the process group is killed
and the exit code is 124, the same code ``timeout(1)`` uses.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

import tiering

HERE = Path(__file__).resolve().parent

# Surface area, an axis orthogonal to tier: which part of the tool a file covers.
SURFACES: dict[str, tuple[str, ...]] = {
    "store": ("test_todo_db.py", "test_todo_migrate.py"),
    "objid": ("test_todo_objid.py", "test_todo_ref.py"),
    "web": ("test_todo_url.py", "test_todo_web_permalink.py", "test_todo_web_render.py"),
    "embed": ("test_todo_embed.py", "test_todo_embed_apple.py"),
    "search": ("test_todo_search.py", "test_todo_search_idf.py"),
    "tag": ("test_todo_tag.py", "test_todo_tag_impl.py"),
    "cli": ("test_todo.py", "test_todo_all_sentinel.py"),
    "meta": ("test_todo_tiering.py",),
}

FAST_TIMEOUT = 60.0
E2E_TIMEOUT = 900.0
TIMEOUT_EXIT = 124


def _files_by_surface() -> dict[str, str]:
    """Map test file -> surface, refusing to run if a file belongs to none.

    A new test file is a deliberate choice of surface, so an unclassified one is
    an error here rather than a file that silently never runs.
    """
    by_file = {name: surface for surface, names in SURFACES.items() for name in names}
    on_disk = {p.name for p in HERE.glob("test_*.py")}
    unknown = sorted(on_disk - set(by_file))
    if unknown:
        sys.exit("run-tests: add these to SURFACES in run-tests.py: " + ", ".join(unknown))
    missing = sorted(set(by_file) - on_disk)
    if missing:
        sys.exit("run-tests: SURFACES names files that do not exist: " + ", ".join(missing))
    return by_file


def _surface_files(surfaces: list[str]) -> list[str]:
    by_file = _files_by_surface()
    if not surfaces:
        return []
    unknown = sorted(set(surfaces) - set(SURFACES))
    if unknown:
        sys.exit(
            f"run-tests: unknown surface(s) {', '.join(unknown)}; "
            f"known: {', '.join(sorted(SURFACES))}"
        )
    return sorted(f for f in by_file if by_file[f] in surfaces)


def _marker_expression(tiers: list[str], run_all: bool) -> str:
    if tiers:
        return " or ".join(sorted(set(tiers)))
    return "" if run_all else "not e2e"


def _limit(expression: str) -> float:
    raw = os.environ.get("TODO_TEST_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            sys.exit(f"run-tests: TODO_TEST_TIMEOUT is not a number: {raw!r}")
    selects_e2e = expression == "" or ("e2e" in expression and "not e2e" not in expression)
    return E2E_TIMEOUT if selects_e2e else FAST_TIMEOUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="include the e2e tier")
    parser.add_argument(
        "--tier", action="append", default=[], metavar="NAME", choices=tiering.TIERS,
        help=f"run one tier only (repeatable): {', '.join(tiering.TIERS)}",
    )
    parser.add_argument(
        "--surface", action="append", default=[], metavar="NAME",
        help=f"run one surface only (repeatable): {', '.join(sorted(SURFACES))}",
    )
    parser.add_argument("--list", action="store_true", help="print the surface map and exit")
    args, pytest_args = parser.parse_known_args()

    if args.list:
        for surface in sorted(SURFACES):
            for name in SURFACES[surface]:
                print(f"{surface:8} {name}")
        return 0

    _files_by_surface()  # fail fast on an unclassified file, whatever the selection
    files = _surface_files(args.surface)
    expression = _marker_expression(args.tier, args.all)
    selection = ["-m", expression] if expression else []

    # Own process group: todo.py shells out to git, so a timeout has to take the
    # children with it.
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-q", *selection, *pytest_args, *files],
        cwd=HERE,
        start_new_session=True,
    )
    try:
        return proc.wait(timeout=_limit(expression))
    except subprocess.TimeoutExpired:
        limit = _limit(expression)
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        print(f"run-tests: timed out after {limit:g}s", file=sys.stderr)
        return TIMEOUT_EXIT


if __name__ == "__main__":
    sys.exit(main())
