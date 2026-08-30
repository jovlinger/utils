# fmt: off
"""Stack VM benchmarks: correctness and timing vs pure Python."""

from __future__ import annotations

import pytest

from tests.stack_bench import (
    ack_c,
    ack_python,
    ack_stacklang,
    bench_triple,
    float_step_sum_c,
    float_step_sum_python,
    float_step_sum_stacklang,
    mandelbrot_ascii,
    mandelbrot_sum_c,
    mandelbrot_sum_python,
    mandelbrot_sum_stacklang,
)


@pytest.mark.slow
def test_ackermann_result_and_timing(capsys) -> None:
    m = 3
    n = 3
    expected = 61
    result = bench_triple(
        "ack",
        lambda: ack_python(m, n),
        lambda: ack_stacklang(m, n),
        lambda: ack_c(m, n),
        repeat=20,
    )
    assert result.python_value == expected
    assert result.stacklang_value == expected
    assert result.c_value == expected
    out = capsys.readouterr().out
    assert "ack:" in out
    assert str(expected) in out
    assert result.python_s > 0.0
    assert result.stacklang_s is not None and result.stacklang_s > 0.0
    assert result.c_s is not None and result.c_s > 0.0


@pytest.mark.slow
def test_float_step_sum_result_and_timing(capsys) -> None:
    stop = 9.5
    step = 0.001
    expected = float_step_sum_python(stop=stop, step=step)
    result = bench_triple(
        "float_step_sum",
        lambda: float_step_sum_python(stop=stop, step=step),
        lambda: float_step_sum_stacklang(stop=stop, step=step),
        lambda: float_step_sum_c(stop=stop, step=step),
        repeat=10,
    )
    assert result.python_value == pytest.approx(expected)
    assert result.stacklang_value == pytest.approx(expected)
    assert result.c_value == pytest.approx(expected)
    out = capsys.readouterr().out
    assert "float_step_sum:" in out
    assert result.python_s > 0.0
    assert result.stacklang_s is not None and result.stacklang_s > 0.0
    assert result.c_s is not None and result.c_s > 0.0


@pytest.mark.slow
def test_mandelbrot_sum_result_and_timing(capsys) -> None:
    width = 48
    height = 24
    max_iter = 32
    expected = mandelbrot_sum_python(width, height, max_iter)
    result = bench_triple(
        "mandel_sum",
        lambda: mandelbrot_sum_python(width, height, max_iter),
        lambda: mandelbrot_sum_stacklang(width, height, max_iter),
        lambda: mandelbrot_sum_c(width, height, max_iter),
        repeat=5,
    )
    assert result.python_value == expected
    assert result.stacklang_value == expected
    assert result.c_value == expected
    out = capsys.readouterr().out
    assert "mandel_sum:" in out
    assert result.python_s > 0.0
    assert result.stacklang_s is not None and result.stacklang_s > 0.0
    assert result.c_s is not None and result.c_s > 0.0

    art = mandelbrot_ascii(width, height, max_iter)
    print("mandelbrot_ascii:")
    print(art)
    ascii_out = capsys.readouterr().out
    assert "#" in ascii_out or "@" in ascii_out
    assert len(art.splitlines()) == height
