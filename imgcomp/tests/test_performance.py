"""Performance tests: fractal scenes at useful sizes with time budgets."""

from __future__ import annotations

import time

import pytest

from imgcomp import NaiveCompositor
from imgcomp.scene import Scene
from tests.fractal_scenes import fractal_gallery_scene, phyllotaxis_spiral, sierpinski_carpet


def _render_seconds(width: int, height: int, scene: Scene) -> float:
    comp = NaiveCompositor(width, height)
    start = time.perf_counter()
    surface = comp.render(scene)
    elapsed = time.perf_counter() - start
    assert surface.width == width
    assert surface.height == height
    return elapsed


@pytest.mark.slow
@pytest.mark.parametrize(
    ("kind", "size", "budget_seconds"),
    [
        ("carpet", 192, 90.0),
        ("rings", 192, 20.0),
        ("spirograph", 192, 25.0),
        ("phyllotaxis", 192, 45.0),
    ],
)
def test_fractal_gallery_render_budget(kind: str, size: int, budget_seconds: float) -> None:
    scene = fractal_gallery_scene(kind, size=size, profile="slow")
    elapsed = _render_seconds(size, size, scene)
    assert elapsed < budget_seconds


@pytest.mark.slow
def test_phyllotaxis_dense_spiral_budget() -> None:
    scene = [phyllotaxis_spiral(dot_count=36, dot_radius=2.0, spread=70.0)]
    elapsed = _render_seconds(192, 192, scene)
    assert elapsed < 35.0


@pytest.mark.slow
def test_sierpinski_deep_carpet_budget() -> None:
    scene = [sierpinski_carpet(3, 70.0, (220, 180, 90, 255))]
    elapsed = _render_seconds(192, 192, scene)
    assert elapsed < 90.0
