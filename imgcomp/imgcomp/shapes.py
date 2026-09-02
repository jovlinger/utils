"""SDF-backed geometry shapes (distance math inlined on each class)."""

from __future__ import annotations

import math
from typing import Optional

from imgcomp.shape import Shape
from imgcomp.rgba import RGBA, WHITE


class SDFShape(Shape):
    """White-filled geometry; subclasses implement ``distance``."""

    def distance(self, x: float, y: float) -> float:
        raise NotImplementedError(f"{type(self).__name__} must implement distance")

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        if self.distance(x, y) <= 0.0:
            return WHITE
        return None


class Circle(SDFShape):
    """Disk centered at the origin."""

    def __init__(self, radius: float) -> None:
        if radius < 0.0:
            raise ValueError("radius must be non-negative")
        self.radius = radius

    def distance(self, x: float, y: float) -> float:
        return math.hypot(x, y) - self.radius


class Rectangle(SDFShape):
    """Axis-aligned rectangle centered at the origin."""

    def __init__(self, half_width: float, half_height: float) -> None:
        if half_width < 0.0 or half_height < 0.0:
            raise ValueError("half_width and half_height must be non-negative")
        self.half_width = half_width
        self.half_height = half_height

    def distance(self, x: float, y: float) -> float:
        qx = abs(x) - self.half_width
        qy = abs(y) - self.half_height
        outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
        inside = min(max(qx, qy), 0.0)
        return outside + inside


class Oval(SDFShape):
    """Axis-aligned ellipse centered at the origin."""

    def __init__(self, radius_x: float, radius_y: float) -> None:
        if radius_x < 0.0 or radius_y < 0.0:
            raise ValueError("radius_x and radius_y must be non-negative")
        self.radius_x = max(radius_x, 1e-9)
        self.radius_y = max(radius_y, 1e-9)

    def distance(self, x: float, y: float) -> float:
        nx = x / self.radius_x
        ny = y / self.radius_y
        scale = min(self.radius_x, self.radius_y)
        return (math.hypot(nx, ny) - 1.0) * scale


class Infinite(Shape):
    """Full-plane geometry of infinite extent; use as a background layer."""

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        return WHITE
