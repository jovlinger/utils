"""Wrapper objects that transform local coordinates for children."""

from __future__ import annotations

import math
from typing import Sequence

from imgcomp.object import Object
from imgcomp.rgba import RGBA, modulate


class Group(Object):
    """Ordered children composited depth-first (later siblings on top)."""

    def __init__(self, children: Sequence[Object]) -> None:
        self.children = tuple(children)

    def sample(self, x: float, y: float) -> RGBA:
        raise NotImplementedError("Group.sample is resolved by NaiveCompositor pull-sampling")

    def hit(self, x: float, y: float) -> bool:
        raise NotImplementedError("Group.hit is resolved by NaiveCompositor pick()")


class Translate(Object):
    """Place the child center at (tx, ty) in parent space."""

    def __init__(self, child: Object, tx: float, ty: float) -> None:
        self.child = child
        self.tx = tx
        self.ty = ty

    def sample(self, x: float, y: float) -> RGBA:
        raise NotImplementedError("Translate.sample is resolved by NaiveCompositor pull-sampling")

    def hit(self, x: float, y: float) -> bool:
        raise NotImplementedError("Translate.hit is resolved by NaiveCompositor pick()")

    def on_touch(self, x: float, y: float) -> None:
        self.child.on_touch(x - self.tx, y - self.ty)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.child.on_drag(x - self.tx, y - self.ty, dx, dy)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.child.on_scroll(x - self.tx, y - self.ty, delta)


class Rotate(Object):
    """Rotate the child about the local origin (degrees, +y down)."""

    def __init__(self, child: Object, degrees: float) -> None:
        self.child = child
        self.degrees = degrees
        self._cos = math.cos(math.radians(degrees))
        self._sin = math.sin(math.radians(degrees))

    def _to_child(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._cos + y * self._sin, -x * self._sin + y * self._cos)

    def _from_child(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._cos - y * self._sin, x * self._sin + y * self._cos)

    def sample(self, x: float, y: float) -> RGBA:
        raise NotImplementedError("Rotate.sample is resolved by NaiveCompositor pull-sampling")

    def hit(self, x: float, y: float) -> bool:
        raise NotImplementedError("Rotate.hit is resolved by NaiveCompositor pick()")

    def on_touch(self, x: float, y: float) -> None:
        cx, cy = self._to_child(x, y)
        self.child.on_touch(cx, cy)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        cx, cy = self._to_child(x, y)
        cdx, cdy = self._to_child(dx, dy)
        self.child.on_drag(cx, cy, cdx, cdy)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        cx, cy = self._to_child(x, y)
        self.child.on_scroll(cx, cy, delta)


class ColorMod(Object):
    """Multiply straight RGBA channels on samples from the child."""

    def __init__(
        self,
        child: Object,
        *,
        r_mul: float = 1.0,
        g_mul: float = 1.0,
        b_mul: float = 1.0,
        a_mul: float = 1.0,
    ) -> None:
        self.child = child
        self.r_mul = r_mul
        self.g_mul = g_mul
        self.b_mul = b_mul
        self.a_mul = a_mul

    def sample(self, x: float, y: float) -> RGBA:
        raise NotImplementedError("ColorMod.sample is resolved by NaiveCompositor pull-sampling")

    def hit(self, x: float, y: float) -> bool:
        raise NotImplementedError("ColorMod.hit is resolved by NaiveCompositor pick()")

    def on_touch(self, x: float, y: float) -> None:
        self.child.on_touch(x, y)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.child.on_drag(x, y, dx, dy)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.child.on_scroll(x, y, delta)
