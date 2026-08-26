"""Wrapper objects that transform local coordinates for children."""

from __future__ import annotations

import math
from typing import Optional

from imgcomp.shape import Shape
from imgcomp.rgba import RGBA, modulate


class Translate(Shape):
    """Place the child center at (tx, ty) in parent space."""

    def __init__(self, child: Shape, tx: float, ty: float) -> None:
        self.child = child
        self.tx = tx
        self.ty = ty

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        return self.child.color_at(x - self.tx, y - self.ty)

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        return self.child.pick_target(x - self.tx, y - self.ty)

    def on_touch(self, x: float, y: float) -> None:
        self.child.on_touch(x - self.tx, y - self.ty)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.child.on_drag(x - self.tx, y - self.ty, dx, dy)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.child.on_scroll(x - self.tx, y - self.ty, delta)


class Rotate(Shape):
    """Rotate the child about the local origin (degrees, +y down)."""

    def __init__(self, child: Shape, degrees: float) -> None:
        self.child = child
        self.degrees = degrees
        self._cos = math.cos(math.radians(degrees))
        self._sin = math.sin(math.radians(degrees))

    def _to_child(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._cos + y * self._sin, -x * self._sin + y * self._cos)

    def _from_child(self, x: float, y: float) -> tuple[float, float]:
        return (x * self._cos - y * self._sin, x * self._sin + y * self._cos)

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        cx, cy = self._to_child(x, y)
        return self.child.color_at(cx, cy)

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        cx, cy = self._to_child(x, y)
        return self.child.pick_target(cx, cy)

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


class Stretch(Shape):
    """Non-uniform scale of the child about the local origin (+y down)."""

    def __init__(self, child: Shape, scale_x: float, scale_y: float) -> None:
        if scale_x == 0.0 or scale_y == 0.0:
            raise ValueError("scale_x and scale_y must be non-zero")
        self.child = child
        self.scale_x = scale_x
        self.scale_y = scale_y

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        return self.child.color_at(x / self.scale_x, y / self.scale_y)

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        return self.child.pick_target(x / self.scale_x, y / self.scale_y)

    def on_touch(self, x: float, y: float) -> None:
        self.child.on_touch(x / self.scale_x, y / self.scale_y)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.child.on_drag(x / self.scale_x, y / self.scale_y, dx / self.scale_x, dy / self.scale_y)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.child.on_scroll(x / self.scale_x, y / self.scale_y, delta)


class Color(Shape):
    """Apply a solid straight RGBA wherever the child is visible."""

    def __init__(self, child: Shape, color: RGBA) -> None:
        self.child = child
        self.color = color

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        if not self.child.color_at(x, y):
            return None
        return self.color

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        return self.child.pick_target(x, y)

    def on_touch(self, x: float, y: float) -> None:
        self.child.on_touch(x, y)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.child.on_drag(x, y, dx, dy)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.child.on_scroll(x, y, delta)


class ColorMod(Shape):
    """Multiply straight RGBA channels on colors from the child."""

    def __init__(
        self,
        child: Shape,
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

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        if not (base := self.child.color_at(x, y)):
            return None
        return modulate(base, self.r_mul, self.g_mul, self.b_mul, self.a_mul)

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        return self.child.pick_target(x, y)

    def on_touch(self, x: float, y: float) -> None:
        self.child.on_touch(x, y)

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        self.child.on_drag(x, y, dx, dy)

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        self.child.on_scroll(x, y, delta)
