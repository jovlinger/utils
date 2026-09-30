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

``$TMPDIR`` is pointed at a memory-backed directory for the run, sized by
``$TODO_TEST_RAMDISK_MB`` and torn down afterwards, so the suite's temporary
stores and git repos do not churn SSD pages. This is best effort: ``--no-ramdisk``
opts out, and a platform that cannot provide one runs against the disk instead.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
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

# Every test builds its store and its git repo under $TMPDIR and deletes them in
# tearDown, so the suite is pure write churn against the SSD. Measured peak for
# the heaviest e2e slice is 192 KB, so this is ~80x headroom.
RAMDISK_MB = 16
RAMDISK_PREFIX = "todotest"


def _run(*argv: str) -> str:
    """Run a setup command, returning stdout; raises on a non-zero exit."""
    return subprocess.run(
        argv, check=True, capture_output=True, text=True
    ).stdout.strip()


@contextlib.contextmanager
def _macos_ramdisk(size_mb: int, mount: Path):
    """An HFS+ RAM disk mounted at *mount*. No sudo needed for any step."""
    device = _run("hdiutil", "attach", "-nomount", f"ram://{size_mb * 2048}").split()[0]
    try:
        _run("newfs_hfs", "-v", RAMDISK_PREFIX, device)
        mount.mkdir(parents=True, exist_ok=True)
        _run("diskutil", "mount", "-mountPoint", str(mount), device)
        try:
            yield mount
        finally:
            subprocess.run(
                ["diskutil", "unmount", "force", str(mount)],
                check=False, capture_output=True,
            )
            mount.rmdir()
    finally:
        # Detach last and unconditionally: a leaked device holds the RAM.
        subprocess.run(["hdiutil", "detach", device], check=False, capture_output=True)


@contextlib.contextmanager
def _shm_dir(mount: Path):
    """A directory on Linux's already-mounted /dev/shm tmpfs, so no mount needed."""
    mount.mkdir(parents=True, exist_ok=True)
    try:
        yield mount
    finally:
        shutil.rmtree(mount, ignore_errors=True)


@contextlib.contextmanager
def ramdisk(size_mb: int):
    """Yield a memory-backed directory for $TMPDIR, or None when unavailable.

    Best effort by design: a machine that cannot give us one still runs the
    suite, just against the disk. Both platforms avoid sudo -- macOS because
    `diskutil mount` accepts a user-owned mount point for a RAM disk, Linux
    because /dev/shm is a tmpfs that is already mounted.
    """
    system = platform.system()
    mount = Path(tempfile.gettempdir()) / f"{RAMDISK_PREFIX}-{os.getpid()}"
    try:
        if system == "Darwin":
            with _macos_ramdisk(size_mb, mount) as path:
                yield path
                return
        if system == "Linux" and Path("/dev/shm").is_dir():
            with _shm_dir(Path("/dev/shm") / f"{RAMDISK_PREFIX}-{os.getpid()}") as path:
                yield path
                return
    except (OSError, subprocess.CalledProcessError, IndexError) as exc:
        print(f"run-tests: no ramdisk ({exc}); using {tempfile.gettempdir()}",
              file=sys.stderr)
        yield None
        return
    print(f"run-tests: no ramdisk recipe for {system}; using "
          f"{tempfile.gettempdir()}", file=sys.stderr)
    yield None


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
    parser.add_argument(
        "--no-ramdisk", action="store_true",
        help="keep $TMPDIR on disk instead of a memory-backed directory",
    )
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

    argv = [sys.executable, "-m", "pytest", "-q", *selection, *pytest_args, *files]
    size_mb = int(os.environ.get("TODO_TEST_RAMDISK_MB", RAMDISK_MB))
    holder = contextlib.nullcontext(None) if args.no_ramdisk else ramdisk(size_mb)
    with holder as tmp:
        env = dict(os.environ)
        if tmp is not None:
            # Every mkdtemp() in the suite honours TMPDIR, so pointing it here
            # moves both the stores and the git repos off the SSD.
            env["TMPDIR"] = str(tmp)
        return _spawn(argv, env, _limit(expression))


def _spawn(argv: list[str], env: dict[str, str], limit: float) -> int:
    # Own process group: todo.py shells out to git, so a timeout has to take the
    # children with it.
    proc = subprocess.Popen(argv, cwd=HERE, env=env, start_new_session=True)
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
