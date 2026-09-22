# fmt: off
"""Affine kernel benchmarks with performance ratchets."""

from __future__ import annotations

import pytest

from tests.affine_bench import bench_compose, bench_transform, print_bench


@pytest.mark.slow
def test_affine_compose_faster_than_python(capsys) -> None:
    result = bench_compose(steps=300, repeat=25)
    assert result.python_value == pytest.approx(result.cython_value, rel=0.0, abs=1e-9)
    print_bench("affine_compose", result)
    out = capsys.readouterr().out
    assert "affine_compose:" in out
    assert result.python_s > 0.0
    assert result.cython_s > 0.0
    assert result.cython_s < result.python_s


@pytest.mark.slow
def test_affine_transform_batch_faster_than_python(capsys) -> None:
    result = bench_transform(n=8192, repeat=30)
    assert result.python_value[0] == pytest.approx(result.cython_value[0], rel=0.0, abs=1e-9)
    assert result.python_value[1] == pytest.approx(result.cython_value[1], rel=0.0, abs=1e-9)
    print_bench("affine_transform_batch", result)
    out = capsys.readouterr().out
    assert "affine_transform_batch:" in out
    assert result.python_s > 0.0
    assert result.cython_s > 0.0
    assert result.cython_s < result.python_s
