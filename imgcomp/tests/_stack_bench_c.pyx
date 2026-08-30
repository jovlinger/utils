# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False
# cython: cdivision=True
"""Test-only C kernels and VM op handlers for stack benchmarks.

Native implementations used by ``tests.stack_bench``:

- ``ack_native`` / ``ack`` opcode: Ackermann in C
- ``mandel_escape_iters`` (internal): one Mandelbrot escape count
- ``mandel_sum_native`` / ``mandel_sum`` opcode: grid sum in C
- ``mandel_pixel`` opcode: one pixel escape count from float coords on stack
- ``float_step_sum_native``: arithmetic series sum in C
- ``int_step_sum_native``: integer arithmetic series sum in C
"""

from libc.stdint cimport int64_t

from imgcomp._stack_c cimport (
    OpHandler,
    _handler,
    data_pop_float,
    data_pop_int,
    data_push_float,
    data_push_int,
)


cdef int64_t ack_c(int64_t m, int64_t n) except? -1:
    """Recursive Ackermann function; -1 is a real result, so exceptions are rechecked."""
    if m == 0:
        return n + 1
    if n == 0:
        return ack_c(m - 1, 1)
    return ack_c(m - 1, ack_c(m, n - 1))


cdef int64_t mandel_escape_iters(double x0, double y0, int max_iter):
    """Return escape iteration count for (x0, y0), capped at max_iter."""
    cdef double zx = 0.0
    cdef double zy = 0.0
    cdef int it = 0
    cdef double mag2
    while it < max_iter:
        mag2 = zx * zx + zy * zy
        if mag2 > 4.0:
            break
        zx, zy = zx * zx - zy * zy + x0, 2.0 * zx * zy + y0
        it += 1
    return it


cdef int64_t mandel_sum_c(int width, int height, int max_iter):
    """Sum escape counts over a width x height grid (standard viewport mapping)."""
    cdef int64_t total = 0
    cdef int py
    cdef int px
    cdef double y0
    cdef double x0
    for py in range(height):
        y0 = (-1.5 + ((<double>py * 2.0) / <double>height))
        for px in range(width):
            x0 = (-2.0 + ((<double>px * 2.5) / <double>width))
            total += mandel_escape_iters(x0, y0, max_iter)
    return total


cdef int64_t int_step_sum_c(int64_t start, int64_t stop, int64_t step):
    """Sum start, start+step, ... while value <= stop."""
    cdef int64_t total = 0
    cdef int64_t value = start
    while value <= stop:
        total += value
        value += step
    return total


cdef double float_step_sum_c(double start, double stop, double step):
    """Sum start, start+step, ... while value <= stop."""
    cdef double total = 0.0
    cdef double value = start
    while value <= stop:
        total += value
        value += step
    return total


cdef int _op_ack() except -1:
    """Stack: m n -- result. Pop m then n; push Ackermann(m, n)."""
    cdef int64_t n = data_pop_int()
    cdef int64_t m = data_pop_int()
    data_push_int(ack_c(m, n))


cdef int _op_mandel_pixel() except -1:
    """Stack: x0 y0 max_iter -- it. Pop max_iter, y0, x0; push escape count."""
    cdef int max_iter = <int>data_pop_int()
    cdef double y0 = data_pop_float()
    cdef double x0 = data_pop_float()
    data_push_int(mandel_escape_iters(x0, y0, max_iter))


cdef int _op_mandel_sum() except -1:
    """Stack: width height max_iter -- total. Pop dims; push grid escape sum."""
    cdef int max_iter = <int>data_pop_int()
    cdef int height = <int>data_pop_int()
    cdef int width = <int>data_pop_int()
    data_push_int(mandel_sum_c(width, height, max_iter))


# VM opcode tokens for register_op("ack", ack), etc.
ack = _handler(_op_ack)
mandel_pixel = _handler(_op_mandel_pixel)
mandel_sum = _handler(_op_mandel_sum)


def ack_native(int64_t m, int64_t n) -> int:
    """Ackermann(m, n) in C without the stack VM."""
    return ack_c(m, n)


def mandel_sum_native(int width, int height, int max_iter) -> int:
    """Sum Mandelbrot escape iterations over a grid in C without the stack VM."""
    return mandel_sum_c(width, height, max_iter)


def int_step_sum_native(int64_t start, int64_t stop, int64_t step) -> int:
    """Sum start, start+step, ... while value <= stop in C without the stack VM."""
    return int_step_sum_c(start, stop, step)


def float_step_sum_native(double start, double stop, double step) -> float:
    """Sum start, start+step, ... while value <= stop in C without the stack VM."""
    return float_step_sum_c(start, stop, step)
