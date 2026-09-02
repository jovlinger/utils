"""Tests for pick() and reactive dispatch."""

from __future__ import annotations

from imgcomp.naive import NaiveCompositor
from imgcomp.shape import Shape
from imgcomp.rgba import RGBA
from imgcomp.shapes import Circle
from imgcomp.wrappers import Color, Translate


class RecordingCircle(Circle):
    def __init__(self, radius: float) -> None:
        super().__init__(radius)
        self.touches: list[tuple[float, float]] = []

    def on_touch(self, x: float, y: float) -> None:
        self.touches.append((x, y))


def test_pick_returns_topmost_hit_in_paint_order() -> None:
    comp = NaiveCompositor(20, 20)
    front = Color(Circle(4.0), (255, 0, 0, 255))
    back = Color(Circle(6.0), (0, 255, 0, 255))
    scene = [back, front]
    picked = comp.pick(scene, 10.5, 10.5)
    assert picked is not None
    assert picked.target is front.child


def test_translate_percolates_local_touch_coords() -> None:
    comp = NaiveCompositor(20, 20)
    target = RecordingCircle(3.0)
    scene = [Color(Translate(target, 4.0, -2.0), (255, 255, 255, 255))]
    handled = comp.dispatch_event(scene, "touch", 14.0, 8.0)
    assert handled is True
    assert target.touches == [(0.0, 0.0)]


class _HitOnly(Shape):
    def __init__(self) -> None:
        self.scrolled = False

    def color_at(self, x: float, y: float) -> RGBA | None:
        return (255, 255, 255, 255)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.scrolled = True


def test_dispatch_scroll_reaches_hit_target() -> None:
    comp = NaiveCompositor(10, 10)
    target = _HitOnly()
    scene = [target]
    assert comp.dispatch_event(scene, "scroll", 5.5, 5.5, delta=1.0) is True
    assert target.scrolled is True
