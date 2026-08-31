# fmt: off
"""Stack VM benchmarks: pure Python, stack-language programs, and native C.

Each workload exposes three implementations where applicable:

- **python**: reference algorithm in Python
- **stacklang**: work driven by stack VM body opcodes (loops, arithmetic, calls)
- **c**: same kernel as the VM primitives, called directly with no interpreter
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable

from imgcomp import _stack_c as _cy
from imgcomp import stack_c as sc
from imgcomp.stack_c import OpHandler, reset_vm
from tests import _stack_bench_c as _bench_c


@dataclass(frozen=True)
class BenchTriple:
    """Correctness values and timed runs for python / stacklang / c."""

    python_value: object
    stacklang_value: object | None
    c_value: object | None
    python_s: float
    stacklang_s: float | None
    c_s: float | None


def register_bench_ops() -> None:
    """Register test-only VM opcodes that wrap native C kernels."""
    sc.ack = sc.register_op("ack", _bench_c.ack)
    sc.mandel_pixel = sc.register_op("mandel_pixel", _bench_c.mandel_pixel)
    sc.mandel_sum = sc.register_op("mandel_sum", _bench_c.mandel_sum)


def _fresh_vm(register: Callable[[], None]) -> None:
    """Reset VM state and register base, bench, and caller opcodes."""
    reset_vm()
    sc.register_base_ops()
    register_bench_ops()
    register()


# --- Ackermann ---------------------------------------------------------------


def ack_python(m: int, n: int) -> int:
    """Ackermann(m, n) in pure Python."""
    if m == 0:
        return n + 1
    if n == 0:
        return ack_python(m - 1, 1)
    return ack_python(m - 1, ack_python(m, n - 1))


def ack_stacklang(m: int, n: int) -> int:
    """Ackermann via the stack VM dispatching the native ``ack`` opcode.

    There is no composed token program for Ackermann; this path measures VM
    overhead around the C kernel.
    """
    _fresh_vm(lambda: None)
    _cy.push_int(n)
    _cy.push_int(m)
    _cy.invoke_op("ack")
    return _cy.pop_int()


def ack_c(m: int, n: int) -> int:
    """Ackermann(m, n) in C with no stack VM."""
    return _bench_c.ack_native(m, n)


# --- Mandelbrot sum ----------------------------------------------------------


def mandelbrot_escape_iters(x0: float, y0: float, max_iter: int) -> int:
    """Escape-time iteration count for one point (pure Python)."""
    zx = 0.0
    zy = 0.0
    it = 0
    while it < max_iter:
        mag2 = zx * zx + zy * zy
        if mag2 > 4.0:
            break
        zx, zy = zx * zx - zy * zy + x0, 2.0 * zx * zy + y0
        it += 1
    return it


def mandelbrot_sum_python(width: int, height: int, max_iter: int) -> int:
    """Sum escape iterations over a width x height grid in pure Python."""
    total = 0
    x_scale = 2.5 / width
    y_scale = 2.0 / height
    for py in range(height):
        y0 = -1.5 + py * y_scale
        for px in range(width):
            x0 = -2.0 + px * x_scale
            total += mandelbrot_escape_iters(x0, y0, max_iter)
    return total


def _register_mandel_composed(width: int, height: int, max_iter: int) -> None:
    x_scale = 2.5 / width
    x_bias = -2.0
    y_scale = 2.0 / height
    y_bias = -1.5
    mandel_px = sc.register_op(
        "mandel_px",
        [
            sc.dup,
            sc.i_to_f,
            x_scale,
            sc.f_mul,
            x_bias,
            sc.f_add,
            sc.swap,
            sc.drop,
            sc.over,
            sc.i_to_f,
            y_scale,
            sc.f_mul,
            y_bias,
            sc.f_add,
            max_iter,
            sc.mandel_pixel,
            1,
            sc.i_add_at,
        ],
    )
    mandel_row = sc.register_op(
        "mandel_row",
        [
            0,
            width - 1,
            1,
            sc.lit_op,
            mandel_px,
            sc.int_incr_le,
            sc.drop,
        ],
    )
    sc.register_op(
        "mandel_sum_composed",
        [
            0,
            0,
            height - 1,
            1,
            sc.lit_op,
            mandel_row,
            sc.int_incr_le,
        ],
    )


def mandelbrot_sum_stacklang(width: int, height: int, max_iter: int) -> int:
    """Sum escape iterations using nested ``int_incr_le`` stack programs."""
    _fresh_vm(lambda: _register_mandel_composed(width, height, max_iter))
    _cy.run_op("mandel_sum_composed")
    return _cy.pop_int()


def mandelbrot_sum_c(width: int, height: int, max_iter: int) -> int:
    """Sum escape iterations in C with no stack VM."""
    return _bench_c.mandel_sum_native(width, height, max_iter)


def mandelbrot_ascii(
    width: int,
    height: int,
    max_iter: int,
    *,
    chars: str = " .:-=+*#%@",
) -> str:
    """Render a simple ASCII Mandelbrot map (pure Python, display only)."""
    lines: list[str] = []
    x_scale = 2.5 / width
    y_scale = 2.0 / height
    for py in range(height):
        y0 = -1.5 + py * y_scale
        row: list[str] = []
        for px in range(width):
            x0 = -2.0 + px * x_scale
            it = mandelbrot_escape_iters(x0, y0, max_iter)
            if it >= max_iter:
                row.append(chars[-1])
                continue
            idx = int(it * (len(chars) - 1) / max_iter)
            row.append(chars[idx])
        lines.append("".join(row))
    return "\n".join(lines)


# --- Float step sum ----------------------------------------------------------


def float_step_sum_python(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> float:
    """Sum start, start+step, ... stop in pure Python."""
    total = 0.0
    value = start
    while value <= stop:
        total = total + value
        value += step
    return total


def _register_float_step_sum(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> None:
    float_step_body = sc.register_op(
        "float_step_body",
        [
            0,
            sc.f_add_at,
        ],
    )
    sc.register_op(
        "float_step_sum",
        [
            0.0,
            start,
            stop,
            step,
            sc.lit_op, float_step_body, # this is lisp's quote. reference float_step_body without invoking it.
            sc.float_incr_le,
        ],
    )


def _register_float_step_sum_while(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> None:
    """Float step sum with ``while`` and loop bounds baked into whilefn/body.

    ``i <= stop`` is exactly ``nextafter(stop) > i``, so the bound is bumped
    once at registration and the test is three ops with no negation.
    """
    float_sum_whilefn = sc.register_op(
        "float_sum_whilefn",
        [
            math.nextafter(stop, math.inf),
            sc.over,
            sc.f_gt,
        ],
    )
    float_sum_while_body = sc.register_op(
        "float_sum_while_body",
        [
            sc.dup,
            1,
            sc.f_add_at,
            step,
            sc.f_add,
        ],
    )
    sc.register_op(
        "float_step_sum_while",
        [
            0.0,
            start,
            float_sum_whilefn,
            float_sum_while_body,
            sc.while_loop,
            sc.drop,
        ],
    )


def _register_float_incr_le_wb() -> OpHandler:
    """``float_incr_le`` as a WordBuf loop via ``while``.

    Stack in: ``acc i imax incr body`` (same as native ``float_incr_le``).
    The quoted ``body`` is dropped; the sum step is ``dup 3 f_add_at`` plus
    ``i += incr``. Layout after preamble: ``acc incr imax i``.
    """
    float_il_whilefn = sc.register_op(
        "float_il_whilefn",
        [
            sc.over,
            sc.over,
            sc.swap,
            sc.f_gt,
            0,
            sc.i_eq,
        ],
    )
    float_il_while_body = sc.register_op(
        "float_il_while_body",
        [
            sc.dup,
            3,
            sc.f_add_at,
            sc.rot,
            sc.over,
            sc.f_add,
            sc.rot,
        ],
    )
    return sc.register_op(
        "float_incr_le_wb",
        [
            sc.drop,
            sc.swap,
            sc.rot,
            sc.swap,
            float_il_whilefn,
            float_il_while_body,
            sc.while_loop,
            sc.drop,
            sc.drop,
            sc.drop,
        ],
    )


def _register_float_step_sum_incr_le_wb(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> None:
    float_step_body = sc.register_op(
        "float_step_body_wb",
        [
            0,
            sc.f_add_at,
        ],
    )
    float_incr_le_wb = _register_float_incr_le_wb()
    sc.register_op(
        "float_step_sum_incr_le_wb",
        [
            0.0,
            start,
            stop,
            step,
            sc.lit_op,
            float_step_body,
            float_incr_le_wb,
        ],
    )


def float_step_sum_stacklang(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> float:
    """Sum start, start+step, ... stop via ``float_incr_le`` and stack float ops."""
    _fresh_vm(lambda: _register_float_step_sum(start=start, stop=stop, step=step))
    _cy.run_op("float_step_sum")
    return _cy.pop_float()


def float_step_sum_while_stacklang(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> float:
    """Sum start, start+step, ... stop via a ``while`` loop (bounds baked in)."""
    _fresh_vm(
        lambda: _register_float_step_sum_while(start=start, stop=stop, step=step)
    )
    _cy.run_op("float_step_sum_while")
    return _cy.pop_float()


def float_step_sum_incr_le_wb_stacklang(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> float:
    """Sum start, start+step, ... stop via WordBuf ``float_incr_le_wb``."""
    _fresh_vm(
        lambda: _register_float_step_sum_incr_le_wb(
            start=start, stop=stop, step=step
        )
    )
    _cy.run_op("float_step_sum_incr_le_wb")
    return _cy.pop_float()


def float_step_sum_c(
    *,
    start: float = 0.0,
    stop: float = 9.5,
    step: float = 0.5,
) -> float:
    """Sum start, start+step, ... stop in C with no stack VM."""
    return _bench_c.float_step_sum_native(start, stop, step)


# --- Int step sum ----------------------------------------------------------


def int_step_sum_python(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> int:
    """Sum start, start+step, ... stop in pure Python."""
    total = 0
    value = start
    while value <= stop:
        total = total + value
        value += step
    return total


def _register_int_step_sum(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> None:
    int_step_body = sc.register_op(
        "int_step_body",
        [
            0,
            sc.i_add_at,
        ],
    )
    sc.register_op(
        "int_step_sum",
        [
            0,
            start,
            stop,
            step,
            sc.lit_op,
            int_step_body,
            sc.int_incr_le,
        ],
    )


def _register_int_step_sum_while(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> None:
    """Int step sum with ``while`` and loop bounds baked into whilefn/body.

    ``i <= stop`` is exactly ``stop + 1 > i`` for integers, so the test is
    three ops with no negation.
    """
    int_sum_whilefn = sc.register_op(
        "int_sum_whilefn",
        [
            stop + 1,
            sc.over,
            sc.i_gt,
        ],
    )
    int_sum_while_body = sc.register_op(
        "int_sum_while_body",
        [
            sc.dup,
            1,
            sc.i_add_at,
            step,
            sc.i_add,
        ],
    )
    sc.register_op(
        "int_step_sum_while",
        [
            0,
            start,
            int_sum_whilefn,
            int_sum_while_body,
            sc.while_loop,
            sc.drop,
        ],
    )


def _register_int_incr_le_wb() -> OpHandler:
    """``int_incr_le`` as a WordBuf loop via ``while``.

    Stack in: ``acc i imax incr body`` (same as native ``int_incr_le``).
    The quoted ``body`` is dropped; layout after preamble: ``acc incr imax+1 i``.
    The preamble bumps ``imax`` once so the test is ``imax + 1 > i``.
    """
    int_il_whilefn = sc.register_op(
        "int_il_whilefn",
        [
            sc.over,
            sc.over,
            sc.i_gt,
        ],
    )
    int_il_while_body = sc.register_op(
        "int_il_while_body",
        [
            sc.dup,
            3,
            sc.i_add_at,
            sc.rot,
            sc.over,
            sc.i_add,
            sc.rot,
        ],
    )
    return sc.register_op(
        "int_incr_le_wb",
        [
            sc.drop,
            sc.swap,
            sc.rot,
            sc.swap,
            1,
            1,
            sc.i_add_at,
            int_il_whilefn,
            int_il_while_body,
            sc.while_loop,
            sc.drop,
            sc.drop,
            sc.drop,
        ],
    )


def _register_int_step_sum_incr_le_wb(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> None:
    int_step_body = sc.register_op(
        "int_step_body_wb",
        [
            0,
            sc.i_add_at,
        ],
    )
    int_incr_le_wb = _register_int_incr_le_wb()
    sc.register_op(
        "int_step_sum_incr_le_wb",
        [
            0,
            start,
            stop,
            step,
            sc.lit_op,
            int_step_body,
            int_incr_le_wb,
        ],
    )


def int_step_sum_stacklang(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> int:
    """Sum start, start+step, ... stop via ``int_incr_le`` and stack int ops."""
    _fresh_vm(lambda: _register_int_step_sum(start=start, stop=stop, step=step))
    _cy.run_op("int_step_sum")
    return _cy.pop_int()


def int_step_sum_while_stacklang(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> int:
    """Sum start, start+step, ... stop via a ``while`` loop (bounds baked in)."""
    _fresh_vm(
        lambda: _register_int_step_sum_while(start=start, stop=stop, step=step)
    )
    _cy.run_op("int_step_sum_while")
    return _cy.pop_int()


def int_step_sum_incr_le_wb_stacklang(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> int:
    """Sum start, start+step, ... stop via WordBuf ``int_incr_le_wb``."""
    _fresh_vm(
        lambda: _register_int_step_sum_incr_le_wb(
            start=start, stop=stop, step=step
        )
    )
    _cy.run_op("int_step_sum_incr_le_wb")
    return _cy.pop_int()


def int_step_sum_c(
    *,
    start: int = 0,
    stop: int = 95,
    step: int = 1,
) -> int:
    """Sum start, start+step, ... stop in C with no stack VM."""
    return _bench_c.int_step_sum_native(start, stop, step)


# --- Driver ----------------------------------------------------------


def bench_triple(
    label: str,
    python_fn: Callable[[], object],
    stacklang_fn: Callable[[], object] | None,
    c_fn: Callable[[], object] | None,
    *,
    repeat: int = 3,
) -> BenchTriple:
    """Run python, stacklang, and c implementations; print values and timings."""
    python_value = python_fn()
    stacklang_value = stacklang_fn() if stacklang_fn is not None else None
    c_value = c_fn() if c_fn is not None else None

    py_start = time.perf_counter()
    for _ in range(repeat):
        python_fn()
    python_s = time.perf_counter() - py_start

    stacklang_s: float | None = None
    if stacklang_fn is not None:
        stack_start = time.perf_counter()
        for _ in range(repeat):
            stacklang_fn()
        stacklang_s = time.perf_counter() - stack_start

    c_s: float | None = None
    if c_fn is not None:
        c_start = time.perf_counter()
        for _ in range(repeat):
            c_fn()
        c_s = time.perf_counter() - c_start

    print(
        f"{label}: python={python_value} stacklang={stacklang_value} c={c_value} "
        f"python_s={python_s:.6f} stacklang_s={stacklang_s} c_s={c_s}"
    )
    return BenchTriple(
        python_value=python_value,
        stacklang_value=stacklang_value,
        c_value=c_value,
        python_s=python_s,
        stacklang_s=stacklang_s,
        c_s=c_s,
    )
