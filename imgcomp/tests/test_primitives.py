"""Tests for Circle, Rectangle, Oval, and ImageObject."""

from __future__ import annotations

from imgcomp.primitives import ImageObject
from imgcomp.rgba import WHITE
from imgcomp.shapes import Circle, Infinite, Oval, Rectangle


def test_circle_color_at_uses_radius_from_center() -> None:
    circle = Circle(3.0)
    assert circle.color_at(0.0, 0.0) == WHITE
    assert circle.color_at(2.9, 0.0) == WHITE
    assert circle.color_at(3.1, 0.0) is None


def test_image_color_at_misses_outside_and_transparent_texels() -> None:
    image = ImageObject.from_rgba_rows(
        [
            [(255, 0, 0, 255), (0, 0, 0, 0)],
            [(0, 0, 0, 0), (0, 0, 255, 255)],
        ]
    )
    assert image.color_at(-0.5, -0.5) == (255, 0, 0, 255)
    assert image.color_at(0.5, -0.5) is None
    assert image.color_at(1.1, 0.0) is None


def test_image_color_at_reads_center_based_texel() -> None:
    image = ImageObject.from_rgba_rows([[(10, 20, 30, 40)]])
    assert image.color_at(0.0, 0.0) == (10, 20, 30, 40)


def test_rectangle_color_at_center_and_corners() -> None:
    rect = Rectangle(4.0, 2.0)
    assert rect.color_at(0.0, 0.0) == WHITE
    assert rect.color_at(4.0, 2.0) == WHITE
    assert rect.color_at(4.1, 0.0) is None


def test_oval_is_wider_than_tall_on_x_axis() -> None:
    oval = Oval(5.0, 2.0)
    assert oval.color_at(4.9, 0.0) == WHITE
    assert oval.color_at(0.0, 1.9) == WHITE
    assert oval.color_at(0.0, 2.1) is None


def test_infinite_color_at_everywhere_is_white() -> None:
    bg = Infinite()
    assert bg.color_at(-1e6, 1e6) == WHITE
    assert bg.color_at(0.0, 0.0) == WHITE


def test_infinite_background_fills_viewport() -> None:
    from imgcomp.naive import NaiveCompositor
    from imgcomp.wrappers import Color

    comp = NaiveCompositor(10, 10)
    surface = comp.render([Color(Infinite(), (100, 100, 100, 255))])
    assert surface.get_pixel(0, 0) == (100, 100, 100, 255)
    assert surface.get_pixel(9, 9) == (100, 100, 100, 255)
