# fmt: off
"""Affine transform benchmarks: pure Python vs Cython cdef kernels."""

from __future__ import annotations

import array
import math
import time
from dataclasses import dataclass
from typing import Callable

from imgcomp.affine import Affine
from tests import _math_bench_c as _bench


@dataclass(frozen=True)
class BenchPair:
    """Correctness values and timed runs for python / cython."""

    python_value: object
    cython_value: object
    python_s: float
    cython_s: float


def _timeit(fn: Callable[[], object], repeat: int) -> tuple[object, float]:
    value: object = None
    start = time.perf_counter()
    for _ in range(repeat):
        value = fn()
    return value, time.perf_counter() - start


def _make_points(n: int) -> tuple[list[float], list[float]]:
    xs = [math.sin(i * 0.013) * 100.0 for i in range(n)]
    ys = [math.cos(i * 0.017) * 80.0 for i in range(n)]
    return xs, ys


def compose_chain_python(steps: int) -> Affine:
    aff = Affine.identity()
    for i in range(steps):
        aff = Affine.translate(0.5, -0.25) @ Affine.stretch(1.001, 0.999) @ Affine.rotate(0.7)
    return aff


def transform_points_python(
    aff: Affine,
    xs: list[float],
    ys: list[float],
) -> tuple[list[float], list[float]]:
    out_x: list[float] = []
    out_y: list[float] = []
    for x, y in zip(xs, ys):
        ox, oy = aff.transform(x, y)
        out_x.append(ox)
        out_y.append(oy)
    return out_x, out_y


def transform_points_cython(
    aff_key: tuple[float, float, float, float, float, float],
    xs: list[float],
    ys: list[float],
) -> tuple[list[float], list[float]]:
    return _bench.transform_batch(
        array.array("d", xs),
        array.array("d", ys),
        *aff_key,
    )


def bench_compose(steps: int = 200, repeat: int = 30) -> BenchPair:
    py_val, py_s = _timeit(lambda: compose_chain_python(steps), repeat)
    cy_val, cy_s = _timeit(lambda: _bench.compose_chain(steps), repeat)
    return BenchPair(py_val.as_key(), cy_val, py_s, cy_s)


def bench_transform(n: int = 4096, repeat: int = 40) -> BenchPair:
    aff = compose_chain_python(40)
    xs, ys = _make_points(n)
    key = aff.as_key()
    py_val, py_s = _timeit(lambda: transform_points_python(aff, xs, ys), repeat)
    cy_val, cy_s = _timeit(lambda: transform_points_cython(key, xs, ys), repeat)
    return BenchPair(py_val, cy_val, py_s, cy_s)


def print_bench(label: str, result: BenchPair) -> None:
    ratio = result.python_s / result.cython_s if result.cython_s > 0.0 else float("inf")
    print(
        f"{label}: python={result.python_s:.4f}s cython={result.cython_s:.4f}s "
        f"speedup={ratio:.2f}x"
    )
