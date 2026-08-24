"""Tests for Circle, Rectangle, Oval, and ImageObject."""

from __future__ import annotations

from imgcomp.primitives import ImageObject
from imgcomp.rgba import WHITE
from imgcomp.shapes import Circle, Infinite, Oval, Rectangle


def test_circle_hit_uses_radius_from_center() -> None:
    circle = Circle(3.0)
    assert circle.sample(0.0, 0.0) == WHITE
    assert circle.hit(2.9, 0.0) is True
    assert circle.hit(3.1, 0.0) is False


def test_image_hit_uses_full_aabb_including_transparent_texels() -> None:
    image = ImageObject.from_rgba_rows(
        [
            [(255, 0, 0, 255), (0, 0, 0, 0)],
            [(0, 0, 0, 0), (0, 0, 255, 255)],
        ]
    )
    assert image.hit(0.0, 0.0) is True
    assert image.hit(0.6, -0.4) is True
    assert image.hit(1.1, 0.0) is False


def test_image_sample_reads_center_based_texel() -> None:
    image = ImageObject.from_rgba_rows([[(10, 20, 30, 40)]])
    assert image.sample(0.0, 0.0) == (10, 20, 30, 40)


def test_rectangle_hits_center_and_corners() -> None:
    rect = Rectangle(4.0, 2.0)
    assert rect.hit(0.0, 0.0) is True
    assert rect.hit(4.0, 2.0) is True
    assert rect.hit(4.1, 0.0) is False


def test_oval_is_wider_than_tall_on_x_axis() -> None:
    oval = Oval(5.0, 2.0)
    assert oval.hit(4.9, 0.0) is True
    assert oval.hit(0.0, 1.9) is True
    assert oval.hit(0.0, 2.1) is False


def test_infinite_hits_everywhere_and_samples_white() -> None:
    bg = Infinite()
    assert bg.hit(-1e6, 1e6) is True
    assert bg.sample(0.0, 0.0) == WHITE


def test_infinite_background_fills_viewport() -> None:
    from imgcomp.naive import NaiveCompositor
    from imgcomp.wrappers import Color

    comp = NaiveCompositor(10, 10)
    surface = comp.render([Color(Infinite(), (100, 100, 100, 255))])
    assert surface.get_pixel(0, 0) == (100, 100, 100, 255)
    assert surface.get_pixel(9, 9) == (100, 100, 100, 255)
