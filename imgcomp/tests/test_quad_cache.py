"""Tests for optional quadtree tile cache."""

from __future__ import annotations

import time

import pytest

from imgcomp import Color, Infinite, NaiveCompositor, Translate
from imgcomp.paint_cache import paint_extension_available
from imgcomp.shapes import Circle


def test_cache_off_by_default() -> None:
    comp = NaiveCompositor(32, 32)
    assert comp.cache is None


def test_quad_cache_matches_naive_pixels() -> None:
    scene = [
        Color(Infinite(), (10, 12, 40, 255)),
        Translate(Color(Circle(6.0), (255, 0, 0, 255)), 8.0, -4.0),
    ]
    naive = NaiveCompositor(48, 36, cache=False)
    cached = NaiveCompositor(48, 36, cache=True)
    left = naive.render(scene)
    right = cached.render(scene)
    for y in range(36):
        for x in range(48):
            assert left.get_pixel(x, y) == right.get_pixel(x, y)


def test_static_tiles_hit_when_mover_changes() -> None:
    bg = Color(Infinite(), (20, 20, 30, 255))
    comp = NaiveCompositor(64, 64, cache=True, cache_tile=8)
    assert comp.cache is not None

    scene0 = [bg, Translate(Color(Circle(5.0), (255, 0, 0, 255)), -20.0, 0.0)]
    comp.render(scene0)
    after_first = comp.cache.stats()
    assert after_first["misses"] > 0
    assert after_first["hits"] == 0

    scene1 = [bg, Translate(Color(Circle(5.0), (255, 0, 0, 255)), 20.0, 0.0)]
    comp.render(scene1)
    after_second = comp.cache.stats()
    assert after_second["hits"] > 0
    assert after_second["misses"] > after_first["misses"]


def test_animation_frames_faster_with_quad_cache() -> None:
    if paint_extension_available():
        pytest.skip("specialized full paint is faster than quad overhead on small scenes")
    width, height = 96, 72
    frames = 10
    bg = Color(Infinite(), (15, 15, 25, 255))
    fg = Color(Circle(7.0), (255, 40, 40, 255))

    cached = NaiveCompositor(width, height, cache=True, cache_tile=8)
    naive = NaiveCompositor(width, height, cache=False)

    # Warm static tiles.
    cached.render([bg, Translate(fg, -30.0, 0.0)])

    t0 = time.perf_counter()
    for i in range(frames):
        cached.render([bg, Translate(fg, -30.0 + float(i) * 6.0, 0.0)])
    cached_dt = time.perf_counter() - t0

    t1 = time.perf_counter()
    for i in range(frames):
        naive.render([bg, Translate(fg, -30.0 + float(i) * 6.0, 0.0)])
    naive_dt = time.perf_counter() - t1

    assert cached_dt < naive_dt * 0.85
