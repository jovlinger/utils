"""SDF-backed geometry shapes (distance math inlined on each class)."""

from __future__ import annotations

import math
from typing import Any, Optional

from imgcomp.shape import AABB, Shape, StackLangBody
from imgcomp.rgba import RGBA, WHITE
from imgcomp.stack_type import PrePost

using_stacklang: bool = False


def set_using_stacklang(on: bool) -> None:
    """Mark whether the stacklang VM is in its native render path."""
    global using_stacklang
    using_stacklang = on


def _assert_not_using_stacklang(method: str) -> None:
    assert not using_stacklang, f"{method} must not run during native stacklang render"


assert_not_stacklang = _assert_not_using_stacklang


class SDFShape(Shape):
    """White-filled geometry; subclasses implement ``distance``."""

    def cachekey(self) -> tuple[Any, ...]:
        return ("sdfshape", type(self).__name__, id(self))

    def distance(self, x: float, y: float) -> float:
        _assert_not_using_stacklang("distance")
        raise NotImplementedError(f"{type(self).__name__} must implement distance")

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        _assert_not_using_stacklang("color_at")
        if self.distance(x, y) <= 0.0:
            return WHITE
        return None

    def distance_stacklang(self) -> StackLangBody:
        """Stacklang with gx gy on stack; leaves signed distance on stack.

        Default falls back to ``call_python_method`` on ``distance``. Shapes with
        native kernels override this and avoid the Python callback.
        """
        return ["call_python_method", "distance"]

    def color_at_stacklang(self) -> StackLangBody:
        """Compose fill from ``distance_stacklang`` via ``sdf_fill_white``.

        ``sdf_fill_white`` leaves opaque ``WHITE`` when distance <= 0, else
        transparent (matching ``color_at``).
        """
        return [
            PrePost(
                ["dup_xy", *self.distance_stacklang(), "sdf_fill_white"],
                pre=["gy", "gx"],
                post=["gy", "gx", "r", "g", "b", "a"],
                label="sdf_color_at",
            )
        ]


class Circle(SDFShape):
    """Disk centered at the origin."""

    def __init__(self, radius: float) -> None:
        if radius < 0.0:
            raise ValueError("radius must be non-negative")
        self.radius = radius

    def distance(self, x: float, y: float) -> float:
        _assert_not_using_stacklang("distance")
        return math.hypot(x, y) - self.radius

    def AABB(self) -> AABB:
        radius = self.radius
        return AABB(-radius, -radius, radius, radius)

    def cachekey(self) -> tuple[Any, ...]:
        return ("circle", self.radius)

    def intersected_by(self, rect: AABB) -> Optional[Shape]:
        if not self.AABB().intersects(rect):
            return None
        return self

    def distance_stacklang(self) -> StackLangBody:
        return [self.radius, "circle_distance"]


class Rectangle(SDFShape):
    """Axis-aligned rectangle centered at the origin."""

    def __init__(self, half_width: float, half_height: float) -> None:
        if half_width < 0.0 or half_height < 0.0:
            raise ValueError("half_width and half_height must be non-negative")
        self.half_width = half_width
        self.half_height = half_height

    def distance(self, x: float, y: float) -> float:
        _assert_not_using_stacklang("distance")
        qx = abs(x) - self.half_width
        qy = abs(y) - self.half_height
        outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
        inside = min(max(qx, qy), 0.0)
        return outside + inside

    def AABB(self) -> AABB:
        return AABB(-self.half_width, -self.half_height, self.half_width, self.half_height)

    def cachekey(self) -> tuple[Any, ...]:
        return ("rect", self.half_width, self.half_height)

    def intersected_by(self, rect: AABB) -> Optional[Shape]:
        if not self.AABB().intersects(rect):
            return None
        return self

    def distance_stacklang(self) -> StackLangBody:
        return [self.half_width, self.half_height, "rectangle_distance"]


class Oval(SDFShape):
    """Axis-aligned ellipse centered at the origin."""

    def __init__(self, radius_x: float, radius_y: float) -> None:
        if radius_x < 0.0 or radius_y < 0.0:
            raise ValueError("radius_x and radius_y must be non-negative")
        self.radius_x = max(radius_x, 1e-9)
        self.radius_y = max(radius_y, 1e-9)

    def distance(self, x: float, y: float) -> float:
        _assert_not_using_stacklang("distance")
        nx = x / self.radius_x
        ny = y / self.radius_y
        scale = min(self.radius_x, self.radius_y)
        return (math.hypot(nx, ny) - 1.0) * scale

    def AABB(self) -> AABB:
        return AABB(-self.radius_x, -self.radius_y, self.radius_x, self.radius_y)

    def cachekey(self) -> tuple[Any, ...]:
        return ("oval", self.radius_x, self.radius_y)

    def intersected_by(self, rect: AABB) -> Optional[Shape]:
        if not self.AABB().intersects(rect):
            return None
        return self

    def distance_stacklang(self) -> StackLangBody:
        return [self.radius_x, self.radius_y, "oval_distance"]


class Infinite(Shape):
    """Full-plane geometry of infinite extent; use as a background layer."""

    def cachekey(self) -> tuple[Any, ...]:
        return ("infinite",)

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        _assert_not_using_stacklang("color_at")
        return WHITE

    def color_at_stacklang(self) -> StackLangBody:
        return [
            PrePost(
                ["fill_white"],
                pre=["gy", "gx"],
                post=["gy", "gx", "r", "g", "b", "a"],
                label="infinite_color_at",
            )
        ]

    def AABB(self) -> Optional[AABB]:
        return None
