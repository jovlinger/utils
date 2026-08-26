"""PIC paint specialization: typed Cython hit path vs Python miss/fallback."""

from __future__ import annotations

import pytest

from imgcomp import Color, Infinite, NaiveCompositor, Translate
from imgcomp.naive import accumulate_pixel
from imgcomp.paint_cache import paint_extension_available
from imgcomp.shapes import Circle
from imgcomp.surface import ArraySurface
from tests.fractal_scenes import fractal_gallery_scene, phyllotaxis_spiral, sierpinski_carpet


pytestmark = pytest.mark.skipif(
    not paint_extension_available(), reason="imgcomp._paint not built"
)


def _render_python(width: int, height: int, scene) -> ArraySurface:
    layers = tuple(scene)
    surface = ArraySurface(width, height)
    for y in range(height):
        local_y = y + 0.5 - height / 2.0
        for x in range(width):
            local_x = x + 0.5 - width / 2.0
            surface.set_pixel(x, y, accumulate_pixel(layers, local_x, local_y))
    return surface


def _assert_same(left: ArraySurface, right: ArraySurface) -> None:
    assert left.width == right.width and left.height == right.height
    for y in range(left.height):
        for x in range(left.width):
            assert left.get_pixel(x, y) == right.get_pixel(x, y)


def test_specialized_paint_matches_python_simple() -> None:
    scene = [
        Color(Infinite(), (10, 12, 40, 255)),
        Translate(Color(Circle(6.0), (255, 0, 0, 255)), 8.0, -4.0),
    ]
    comp = NaiveCompositor(48, 36)
    _assert_same(comp.render(scene), _render_python(48, 36, scene))


@pytest.mark.parametrize("kind", ["carpet", "rings", "spirograph", "phyllotaxis"])
def test_specialized_paint_matches_python_gallery(kind: str) -> None:
    scene = fractal_gallery_scene(kind, size=96, profile="fast")
    comp = NaiveCompositor(96, 96)
    _assert_same(comp.render(scene), _render_python(96, 96, scene))


def test_specialized_paint_matches_phyllotaxis_and_sierpinski() -> None:
    for scene, size in (
        ([phyllotaxis_spiral(18, 2.0, 40.0)], 64),
        ([sierpinski_carpet(2, 30.0, (220, 180, 90, 255))], 64),
    ):
        comp = NaiveCompositor(size, size)
        _assert_same(comp.render(scene), _render_python(size, size, scene))


def test_pic_hit_on_second_identical_render() -> None:
    scene = [
        Color(Infinite(), (10, 12, 40, 255)),
        Translate(Color(Circle(6.0), (255, 0, 0, 255)), 8.0, -4.0),
    ]
    comp = NaiveCompositor(32, 32)
    comp.render(scene)
    after_miss = comp.paint_cache.stats()
    assert after_miss["misses"] == 1
    assert after_miss["hits"] == 0
    comp.render(scene)
    after_hit = comp.paint_cache.stats()
    assert after_hit["hits"] == 1
    assert after_hit["misses"] == 1


def test_quad_and_specialized_paint_agree() -> None:
    scene = [
        Color(Infinite(), (10, 12, 40, 255)),
        Translate(Color(Circle(6.0), (255, 0, 0, 255)), 8.0, -4.0),
    ]
    naive = NaiveCompositor(48, 36, cache=False)
    cached = NaiveCompositor(48, 36, cache=True)
    _assert_same(naive.render(scene), cached.render(scene))
