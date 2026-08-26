"""Parity tests for Cython leaf math vs pure Python."""

from __future__ import annotations

import math

import pytest

from imgcomp.native_math import (
    circle_distance,
    native_available,
    oval_distance,
    rectangle_distance,
    set_pixel_rgba,
    src_over_channels,
)
from imgcomp.rgba import src_over as src_over_py
from imgcomp.surface import ArraySurface


pytestmark = pytest.mark.skipif(not native_available(), reason="imgcomp._math not built")


def test_circle_distance_matches_python() -> None:
    for x, y, r in ((0.0, 0.0, 5.0), (3.0, 4.0, 5.0), (10.0, 0.0, 2.0)):
        assert circle_distance(x, y, r) == pytest.approx(math.hypot(x, y) - r)


def test_rectangle_distance_matches_python() -> None:
    hw, hh = 4.0, 2.0
    for x, y in ((0.0, 0.0), (5.0, 0.0), (0.0, 3.0), (5.0, 3.0), (1.0, 1.0)):
        qx = abs(x) - hw
        qy = abs(y) - hh
        expected = math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0)
        assert rectangle_distance(x, y, hw, hh) == pytest.approx(expected)


def test_oval_distance_matches_python() -> None:
    rx, ry = 8.0, 3.0
    for x, y in ((0.0, 0.0), (8.0, 0.0), (0.0, 3.0), (4.0, 1.5)):
        nx = x / rx
        ny = y / ry
        expected = (math.hypot(nx, ny) - 1.0) * min(rx, ry)
        assert oval_distance(x, y, rx, ry) == pytest.approx(expected)


def test_src_over_matches_python() -> None:
    cases = [
        ((10, 20, 30, 255), (255, 0, 0, 0)),
        ((10, 20, 30, 255), (255, 0, 0, 255)),
        ((10, 20, 30, 255), (255, 0, 0, 128)),
        ((0, 0, 0, 0), (100, 50, 25, 200)),
    ]
    for dst, src in cases:
        native = src_over_channels(*dst, *src)
        assert native is not None
        assert native == src_over_py(dst, src)


def test_set_pixel_rgba_writes_buffer() -> None:
    surface = ArraySurface(2, 2)
    assert set_pixel_rgba(surface.pixel_buffer(), 0, 1, 2, 3, 4)
    assert surface.get_pixel(0, 0) == (1, 2, 3, 4)
