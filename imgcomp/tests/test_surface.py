"""Tests for ArraySurface."""

from __future__ import annotations

from imgcomp.rgba import TRANSPARENT
from imgcomp.surface import ArraySurface


def test_array_surface_round_trip_pixel() -> None:
    surface = ArraySurface(2, 2)
    surface.set_pixel(1, 0, (1, 2, 3, 4))
    assert surface.get_pixel(1, 0) == (1, 2, 3, 4)
    assert surface.get_pixel(0, 0) == TRANSPARENT


def test_array_surface_to_bytes_length() -> None:
    surface = ArraySurface(3, 2, fill=(9, 8, 7, 6))
    assert len(surface.to_bytes()) == 3 * 2 * 4
