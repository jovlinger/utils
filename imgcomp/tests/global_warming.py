#!/usr/bin/env venv-run
"""Untimed warmup for this branch's bench render and stack paths."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.bench_render import ALL_BENCHMARK_NAMES, BENCHMARKS, bench_render_path

MIN_SIZE = 16.0


def warm_render_benchmarks() -> str:
    """Untimed render of every fractal benchmark scene for this branch's path."""
    path = bench_render_path()
    for name in ALL_BENCHMARK_NAMES:
        spec = BENCHMARKS[name]
        path.render(
            spec.scene(),
            spec.width,
            spec.height,
            min_size=MIN_SIZE,
        )
    return path.key


def warm_stack_benchmarks() -> str | None:
    """Untimed stack workloads for this branch's stack bench path, if defined."""
    try:
        from tests.bench_stack_run import BENCH_STACK_KEY, warm_stack_workloads
    except ImportError:
        return None
    warm_stack_workloads()
    return BENCH_STACK_KEY


def warm_all() -> tuple[str, str | None]:
    """Warm render and stack bench paths in this process (untimed)."""
    render_key = warm_render_benchmarks()
    stack_key = warm_stack_benchmarks()
    return render_key, stack_key


def main() -> int:
    render_key, stack_key = warm_all()
    parts = [f"render={render_key}"]
    if stack_key is not None:
        parts.append(f"stack={stack_key}")
    print(f"global-warming: {' '.join(parts)} scenes={len(ALL_BENCHMARK_NAMES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
