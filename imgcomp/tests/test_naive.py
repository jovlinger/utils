"""Tests for NaiveCompositor paint order."""

from __future__ import annotations

from imgcomp.naive import NaiveCompositor
from imgcomp.shapes import Circle
from imgcomp.wrappers import Color


def test_later_sibling_paints_on_top() -> None:
    comp = NaiveCompositor(10, 10)
    scene = [
        Color(Circle(4.0), (255, 0, 0, 255)),
        Color(Circle(4.0), (0, 255, 0, 255)),
    ]
    surface = comp.render(scene)
    center = surface.get_pixel(5, 5)
    assert center == (0, 255, 0, 255)
