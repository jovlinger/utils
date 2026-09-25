"""Exclusive store lock: reentrant in-process, exclusive across processes."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _load():
    spec = importlib.util.spec_from_file_location("shadup_lock_under_test", SHADUP_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_store_lock_is_reentrant(tmp_path: Path) -> None:
    shadup = _load()
    shadir = tmp_path / "store"
    with shadup.exclusive_store_lock(str(shadir)):
        with shadup.exclusive_store_lock(str(shadir)):
            assert (shadir / "data" / ".shadup.lock").is_file()
            assert not (shadir / ".shadup.lock").exists()
    assert shadup._store_lock_depth == 0


def test_store_lock_blocks_another_process(tmp_path: Path) -> None:
    shadir = tmp_path / "store"
    shadir.mkdir()
    holder = textwrap.dedent(
        f"""
        import importlib.util
        import time
        spec = importlib.util.spec_from_file_location("shadup_lock_holder", {str(SHADUP_PY)!r})
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with module.exclusive_store_lock({str(shadir)!r}):
            print("held", flush=True)
            time.sleep(1.5)
        print("released", flush=True)
        """
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", holder],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert proc.stdout is not None
    line = proc.stdout.readline()
    assert line.strip() == "held"

    shadup = _load()
    started = time.monotonic()
    acquired: list[float] = []

    def _acquire() -> None:
        with shadup.exclusive_store_lock(str(shadir)):
            acquired.append(time.monotonic())

    thread = threading.Thread(target=_acquire)
    thread.start()
    time.sleep(0.4)
    assert acquired == []
    thread.join(timeout=5)
    proc.wait(timeout=5)
    assert proc.returncode == 0
    assert acquired
    assert acquired[0] - started >= 0.4
