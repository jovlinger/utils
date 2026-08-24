"""Guard tests for Object, Surface, and Compositor ABC seams."""

from __future__ import annotations

import inspect

from imgcomp.compositor import Compositor
from imgcomp.naive import NaiveCompositor
from imgcomp.object import Object
from imgcomp.primitives import Circle
from imgcomp.rgba import TRANSPARENT
from imgcomp.surface import ArraySurface, Surface


def test_object_and_surface_are_abstract() -> None:
    assert inspect.isabstract(Object)
    assert inspect.isabstract(Surface)
    assert inspect.isabstract(Compositor)


def test_array_surface_does_not_require_numpy() -> None:
    surface = ArraySurface(1, 1)
    assert surface.get_pixel(0, 0) == TRANSPARENT


def test_compositor_viewport_to_root_local_uses_center() -> None:
    comp = NaiveCompositor(10, 8)
    assert comp.viewport_to_root_local(5.5, 4.5) == (0.5, 0.5)


def test_circle_sample_and_hit_are_independent() -> None:
    circle = Circle(radius=2.0, color=(255, 0, 0, 255), hit_radius=5.0)
    assert circle.sample(4.0, 0.0) == TRANSPARENT
    assert circle.hit(4.0, 0.0) is True
