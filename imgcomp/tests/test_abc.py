"""Guard tests for Shape, Surface, and Compositor ABC seams."""

from __future__ import annotations

import inspect

from imgcomp.compositor import Compositor
from imgcomp.naive import NaiveCompositor
from imgcomp.rgba import TRANSPARENT, WHITE
from imgcomp.shape import Shape
from imgcomp.shapes import Circle
from imgcomp.surface import ArraySurface, Surface


def test_shape_and_surface_are_abstract() -> None:
    assert inspect.isabstract(Shape)
    assert inspect.isabstract(Surface)
    assert inspect.isabstract(Compositor)


def test_array_surface_does_not_require_numpy() -> None:
    surface = ArraySurface(1, 1)
    assert surface.get_pixel(0, 0) == TRANSPARENT


def test_compositor_viewport_to_root_local_uses_center() -> None:
    comp = NaiveCompositor(10, 8)
    assert comp.viewport_to_root_local(5.5, 4.5) == (0.5, 0.5)


def test_geometry_is_white_until_color_sets_it() -> None:
    circle = Circle(2.0)
    assert circle.sample(0.0, 0.0) == WHITE
    colored = circle.color((255, 0, 0, 255))
    comp = NaiveCompositor(10, 10)
    assert comp.render([colored]).get_pixel(5, 5) == (255, 0, 0, 255)
    assert circle.sample(2.1, 0.0) == TRANSPARENT
    assert circle.hit(2.1, 0.0) is False


def test_shape_operator_methods_chain_like_wrappers() -> None:
    comp = NaiveCompositor(20, 20)
    scene = [Circle(2.0).translate(5.0, 0.0).color((255, 0, 0, 255))]
    surface = comp.render(scene)
    assert surface.get_pixel(15, 10) == (255, 0, 0, 255)
    assert surface.get_pixel(10, 10) == (0, 0, 0, 0)


def test_operator_methods_return_new_shapes_without_mutating_self() -> None:
    circle = Circle(3.0)
    moved = circle.translate(4.0, 0.0)
    painted = circle.color((255, 0, 0, 255))
    assert moved is not circle
    assert painted is not circle
    assert circle.sample(0.0, 0.0) == WHITE
    assert circle.hit(2.9, 0.0) is True
