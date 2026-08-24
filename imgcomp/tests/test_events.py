"""Tests for pick() and reactive dispatch."""

from __future__ import annotations

from imgcomp.naive import NaiveCompositor
from imgcomp.object import Object
from imgcomp.primitives import Circle
from imgcomp.rgba import RGBA, TRANSPARENT
from imgcomp.wrappers import Group, Translate


class RecordingCircle(Circle):
    def __init__(self, radius: float, color: tuple[int, int, int, int], **kwargs: object) -> None:
        super().__init__(radius, color, **kwargs)
        self.touches: list[tuple[float, float]] = []

    def on_touch(self, x: float, y: float) -> None:
        self.touches.append((x, y))


def test_pick_returns_topmost_hit_in_paint_order() -> None:
    comp = NaiveCompositor(20, 20)
    front = Circle(4.0, (255, 0, 0, 255))
    back = Circle(6.0, (0, 255, 0, 255))
    scene = Group((back, front))
    picked = comp.pick(scene, 10.5, 10.5)
    assert picked is not None
    assert picked.target is front


def test_translate_percolates_local_touch_coords() -> None:
    comp = NaiveCompositor(20, 20)
    target = RecordingCircle(3.0, (255, 255, 255, 255))
    scene = Group((Translate(target, 4.0, -2.0),))
    handled = comp.dispatch_event(scene, "touch", 14.0, 8.0)
    assert handled is True
    assert target.touches == [(0.0, 0.0)]


class _HitOnly(Object):
    def __init__(self) -> None:
        self.scrolled = False

    def sample(self, x: float, y: float) -> RGBA:
        return TRANSPARENT

    def hit(self, x: float, y: float) -> bool:
        return True

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.scrolled = True


def test_dispatch_scroll_reaches_hit_target() -> None:
    comp = NaiveCompositor(10, 10)
    target = _HitOnly()
    scene = Group((target,))
    assert comp.dispatch_event(scene, "scroll", 5.5, 5.5, delta=1.0) is True
    assert target.scrolled is True
