# fmt: off
"""Benchmark table for imgcomp._math cdef affine kernels."""

from __future__ import annotations

import array
import time
from dataclasses import dataclass
from typing import Callable

from tests import _math_bench_c as _bench

MIN_SECONDS = 0.5
BATCH_LENGTHS = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 4096, 8192)
OPT = "[x]"


@dataclass(frozen=True)
class Row:
    operation: str
    impl: str
    ns_per_op: float
    total_s: float
    ops: int
    optimal: bool
    note: str = ""


def _grid(n: int) -> tuple[array.array[float], array.array[float]]:
    xs = array.array("d", (((i % 97) - 48) * 0.25 for i in range(n)))
    ys = array.array("d", (((i % 83) - 41) * 0.31 for i in range(n)))
    return xs, ys


def _row_key(row: Row) -> str:
    if row.note:
        return "%s:%s" % (row.operation, row.note)
    return row.operation


def _time_until(min_s: float, fn: Callable[[], object], ops_per_call: int) -> tuple[object, float, int]:
    value: object = None
    calls = 1
    while True:
        for _ in range(3):
            fn()
        start = time.perf_counter()
        for _ in range(calls):
            value = fn()
        elapsed = time.perf_counter() - start
        if elapsed >= min_s or calls >= 50_000_000:
            return value, elapsed, calls * ops_per_call
        calls *= 2


def _row(
    operation: str,
    impl: str,
    total_s: float,
    ops: int,
    optimal: bool,
    note: str = "",
) -> Row:
    return Row(
        operation=operation,
        impl=impl,
        ns_per_op=(total_s * 1e9 / ops) if ops else 0.0,
        total_s=total_s,
        ops=ops,
        optimal=optimal,
        note=note,
    )


def run_all() -> list[Row]:
    rows: list[Row] = []
    steps = 10_000

    def _mat_mul() -> float:
        checksum, _ = _bench.bench_mat_mul(steps)
        return checksum

    _, t, ops = _time_until(MIN_SECONDS, _mat_mul, steps)
    rows.append(_row("affine_mat_mul", "cython inline", t, ops, True))

    def _mat_vec() -> float:
        checksum, _ = _bench.bench_mat_vec_xy(steps)
        return checksum

    _, t, ops = _time_until(MIN_SECONDS, _mat_vec, steps)
    rows.append(_row("affine_mat_vec_xy", "cython inline", t, ops, True))

    for n in BATCH_LENGTHS:
        xs, ys = _grid(n)

        def _batch() -> float:
            checksum, _ = _bench.bench_mat_vec_batch(xs, ys, 1)
            return checksum

        _, t, ops = _time_until(MIN_SECONDS, _batch, n)
        rows.append(
            _row(
                "affine_mat_vec_batch",
                "cython inline (%s)" % _bench.simd_backend(),
                t,
                ops,
                True,
                "n=%d" % n,
            )
        )

    winners: dict[str, float] = {}
    for row in rows:
        key = _row_key(row)
        best = winners.get(key)
        if best is None or row.ns_per_op < best:
            winners[key] = row.ns_per_op
    return [
        Row(
            operation=row.operation,
            impl=row.impl,
            ns_per_op=row.ns_per_op,
            total_s=row.total_s,
            ops=row.ops,
            optimal=row.ns_per_op <= winners[_row_key(row)] * 1.01,
            note=row.note,
        )
        for row in rows
    ]


def print_table(rows: list[Row]) -> None:
    print("imgcomp._math benchmark (>= %.1fs per row, ns/op)" % MIN_SECONDS)
    print()
    print("| operation | impl | ns/op | total_s | note | optimal |")
    print("|-----------|------|------:|--------:|------|:-------:|")
    for row in rows:
        mark = OPT if row.optimal else ""
        print(
            "| %s | %s | %.2f | %.3f | %s | %s |"
            % (row.operation, row.impl, row.ns_per_op, row.total_s, row.note, mark)
        )


if __name__ == "__main__":
    print_table(run_all())
