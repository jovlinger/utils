#!/usr/bin/env venv-run
"""Stack VM benchmarks: timed repetitions only (global warming is ``make build-ext``)."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tests.bench_expected import EXPECTED_STACK_VALUES
from tests.bench_stack import (
    ack_python,
    float_step_sum_python,
    int_step_sum_python,
    mandelbrot_sum_python,
)

DEFAULT_OUTPUT = Path("demo-output-bench-stack")
TIMINGS_FILE = "timings.json"
BENCH_STACK_KEY = "python"
REPEAT = 3

PathFn = Callable[[], object]


@dataclass(frozen=True)
class StackWorkload:
    name: str
    fn: PathFn


WORKLOADS: tuple[StackWorkload, ...] = (
    StackWorkload("ack", lambda: ack_python(3, 3)),
    StackWorkload(
        "float_step_sum",
        lambda: float_step_sum_python(stop=9.5, step=0.00001),
    ),
    StackWorkload("int_step_sum", lambda: int_step_sum_python(stop=950000, step=1)),
    StackWorkload(
        "mandel_sum",
        lambda: mandelbrot_sum_python(48, 24, 32),
    ),
)


def warm_stack_workloads() -> None:
    for workload in WORKLOADS:
        workload.fn()


def _values_match(got: object, expected: int | float) -> bool:
    if isinstance(expected, float):
        return isinstance(got, (int, float)) and math.isclose(
            float(got), expected, rel_tol=0.0, abs_tol=1e-6
        )
    return got == expected


def time_path(fn: PathFn, *, repeat: int) -> tuple[object, float, float, list[float]]:
    timed_wall_start = time.perf_counter()
    iteration_seconds: list[float] = []
    value: object = None
    for _ in range(repeat):
        iter_start = time.perf_counter()
        value = fn()
        iteration_seconds.append(time.perf_counter() - iter_start)
    timed_wall_s = time.perf_counter() - timed_wall_start
    return value, timed_wall_s, sum(iteration_seconds), iteration_seconds


def run_all(*, repeat: int) -> dict[str, Any]:
    results: dict[str, Any] = {
        "path": BENCH_STACK_KEY,
        "repeat": repeat,
        "workloads": {},
    }
    for workload in WORKLOADS:
        value, timed_wall_s, self_s, iter_s = time_path(workload.fn, repeat=repeat)
        expected = EXPECTED_STACK_VALUES[workload.name]
        if not _values_match(value, expected):
            raise RuntimeError(
                f"{workload.name}: {BENCH_STACK_KEY} value={value!r} expected {expected!r}"
            )
        results["workloads"][workload.name] = {
            "value": value,
            "iter_s": iter_s,
            "total_s": self_s,
            "timed_wall_s": timed_wall_s,
            "wall_minus_self_s": timed_wall_s - self_s,
            "value_ok": True,
        }
        print(
            f"{workload.name}: {BENCH_STACK_KEY}_iter_s={iter_s} "
            f"{BENCH_STACK_KEY}_total_s={self_s:.6f} "
            f"wall={timed_wall_s:.6f}s delta={timed_wall_s - self_s:.6f}s "
            f"value={value!r}"
        )
    return results


def record_run(results: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timings_path = output_dir / TIMINGS_FILE
    payload = {
        "current": {
            "run_at": datetime.now(timezone.utc).isoformat(),
            **results,
        },
        "history": [],
    }
    timings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return timings_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=REPEAT, help="timed repetitions")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output directory for {TIMINGS_FILE}",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    results = run_all(repeat=args.repeat)
    timings_path = record_run(results, args.output)
    print(f"stack timings: {timings_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
