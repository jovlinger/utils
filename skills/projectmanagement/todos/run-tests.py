#!/usr/bin/env python3
"""Timeboxed pytest driver for the todos CLI, grouped by surface area.

Plain ``./run-tests.py`` is the fast suite: every surface, minus the files whose
cost is CLI subprocess spawns (measured at 0.24s each, which is 91% of the slow
files' wall time). ``--all`` adds those back. ``--surface web --surface store``
runs named surfaces only, slow files included.

The run is capped at ``$TODO_TEST_TIMEOUT`` seconds, defaulting to 60 for the
fast suite and 900 for ``--all``. On expiry the process group is killed and the
exit code is 124, the same code ``timeout(1)`` uses. Unrecognised arguments pass
through to pytest, so ``./run-tests.py --surface store -k redirect -vv`` works.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SURFACES: dict[str, tuple[str, ...]] = {
    "store": ("test_todo_db.py", "test_todo_migrate.py"),
    "objid": ("test_todo_objid.py", "test_todo_ref.py"),
    "web": ("test_todo_url.py", "test_todo_web_permalink.py", "test_todo_web_render.py"),
    "embed": ("test_todo_embed.py", "test_todo_embed_apple.py"),
    "search": ("test_todo_search.py", "test_todo_search_idf.py"),
    "tag": ("test_todo_tag.py", "test_todo_tag_impl.py"),
    "cli": ("test_todo.py", "test_todo_all_sentinel.py"),
}

# Dominated by out-of-process `todo.py` invocations: test_todo.py alone runs
# 5m46s for 373 tests. Held out of the fast suite, kept under --all.
SLOW: frozenset[str] = frozenset(
    {
        "test_todo.py",
        "test_todo_search.py",
        "test_todo_search_idf.py",
        "test_todo_tag_impl.py",
    }
)

FAST_TIMEOUT = 60.0
ALL_TIMEOUT = 900.0
TIMEOUT_EXIT = 124


def _classified() -> dict[str, str]:
    """Map test file -> surface, refusing to run if a file belongs to none.

    A new test file is a deliberate choice of surface, so an unclassified one is
    an error here rather than a file that silently never runs.
    """
    by_file = {name: surface for surface, names in SURFACES.items() for name in names}
    on_disk = {p.name for p in HERE.glob("test_*.py")}
    unknown = sorted(on_disk - set(by_file))
    if unknown:
        sys.exit(
            "run-tests: add these to SURFACES in run-tests.py: " + ", ".join(unknown)
        )
    missing = sorted(set(by_file) - on_disk)
    if missing:
        sys.exit("run-tests: SURFACES names files that do not exist: " + ", ".join(missing))
    return by_file


def _select(surfaces: list[str], run_all: bool) -> list[str]:
    by_file = _classified()
    if surfaces:
        unknown = sorted(set(surfaces) - set(SURFACES))
        if unknown:
            sys.exit(
                f"run-tests: unknown surface(s) {', '.join(unknown)}; "
                f"known: {', '.join(sorted(SURFACES))}"
            )
        chosen = [f for f in by_file if by_file[f] in surfaces]
    else:
        chosen = [f for f in by_file if run_all or f not in SLOW]
    return sorted(chosen)


def _limit(run_all: bool, whole_suite: bool) -> float:
    raw = os.environ.get("TODO_TEST_TIMEOUT", "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            sys.exit(f"run-tests: TODO_TEST_TIMEOUT is not a number: {raw!r}")
    return ALL_TIMEOUT if (run_all or whole_suite) else FAST_TIMEOUT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="include the slow CLI files")
    parser.add_argument(
        "--surface", action="append", default=[], metavar="NAME",
        help=f"run one surface only (repeatable): {', '.join(sorted(SURFACES))}",
    )
    parser.add_argument(
        "--list", action="store_true", help="print the surface map and exit"
    )
    args, pytest_args = parser.parse_known_args()

    if args.list:
        for surface in sorted(SURFACES):
            for name in SURFACES[surface]:
                print(f"{surface:8} {name}{'  [slow]' if name in SLOW else ''}")
        return 0

    files = _select(args.surface, args.all)
    slow_selected = bool(set(files) & SLOW)
    limit = _limit(args.all, slow_selected)

    # Own process group: todo.py shells out to git, so a timeout has to take the
    # children with it.
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-q", *pytest_args, *files],
        cwd=HERE,
        start_new_session=True,
    )
    try:
        return proc.wait(timeout=limit)
    except subprocess.TimeoutExpired:
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
