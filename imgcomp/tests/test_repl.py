"""Tests for visual REPL session and layer cache."""

from __future__ import annotations

import time

from imgcomp.repl import LayerCache, ReplSession
from imgcomp.shapes import Circle
from imgcomp.wrappers import Color, Translate


def test_run_line_builds_scene_and_renders() -> None:
    session = ReplSession(40, 40)
    result = session.run_line(
        "show(color(circle(8), 40, 40, 40), move(color(circle(5), 255, 0, 0), 10, 0))"
    )
    assert result.ok
    assert session.last_error is None
    surface = session.render()
    # Red circle center is near (30, 20) in viewport pixels for 40x40.
    assert surface.get_pixel(30, 20) == (255, 0, 0, 255)


def test_failed_eval_keeps_prior_scene() -> None:
    session = ReplSession(20, 20)
    assert session.run_line("show(color(circle(4), 0, 255, 0))").ok
    before = session.render().get_pixel(10, 10)
    bad = session.run_line("show(no_such_name)")
    assert bad.ok is False
    assert bad.error is not None
    assert session.render().get_pixel(10, 10) == before


def test_layer_cache_reuses_unchanged_layer() -> None:
    cache = LayerCache(30, 30)
    bg = Color(Circle(12.0), (20, 20, 20, 255))
    fg = Translate(Color(Circle(4.0), (255, 0, 0, 255)), 0.0, 0.0)
    scene = [bg, fg]
    cache.render(scene)
    assert cache.misses == 2
    assert cache.hits == 0

    # Move only the front layer; background key unchanged.
    scene2 = [bg, Translate(Color(Circle(4.0), (255, 0, 0, 255)), 5.0, 0.0)]
    cache.render(scene2)
    assert cache.hits == 1
    assert cache.misses == 3
    assert cache.stats()["entries"] == 3


def test_cached_render_matches_naive() -> None:
    session = ReplSession(24, 24)
    session.run_line(
        "show(color(circle(10), 10, 10, 80), move(color(circle(3), 255, 255, 0), 6, -4))"
    )
    cached = session.render(use_cache=True)
    naive = session.render(use_cache=False)
    for y in range(24):
        for x in range(24):
            assert cached.get_pixel(x, y) == naive.get_pixel(x, y)


def test_moving_layer_faster_with_cache_than_full_naive() -> None:
    """Repeated frames with one mover: layer cache beats full naive re-render."""
    width, height = 80, 60
    frames = 8
    session = ReplSession(width, height)
    session.run_line("bg = color(circle(28), 30, 30, 50)")
    session.run_line("fg = color(circle(6), 255, 0, 0)")

    def build_scene(tx: float) -> None:
        session.run_line(f"show(bg, move(fg, {tx}, 0))")

    build_scene(0.0)
    # Warm cache with background.
    session.render(use_cache=True)

    t0 = time.perf_counter()
    for i in range(frames):
        build_scene(float(i))
        session.render(use_cache=True)
    cached_dt = time.perf_counter() - t0

    t1 = time.perf_counter()
    for i in range(frames):
        build_scene(float(i))
        session.render(use_cache=False)
    naive_dt = time.perf_counter() - t1

    # Cache should be clearly faster when only the front layer moves.
    assert cached_dt < naive_dt * 0.85
