"""SDF-backed geometry objects (white fill until wrapped in Color)."""

from __future__ import annotations

from imgcomp.object import Object
from imgcomp.rgba import TRANSPARENT, WHITE
from imgcomp.sdf import (
    CircleSDF,
    OvalSDF,
    RectangleSDF,
    SDF,
)


class SDFShape(Object):
    """White-filled geometry from an SDF."""

    def __init__(self, sdf: SDF) -> None:
        self.sdf = sdf

    def sample(self, x: float, y: float) -> tuple[int, int, int, int]:
        if self.sdf.distance(x, y) <= 0.0:
            return WHITE
        return TRANSPARENT

    def hit(self, x: float, y: float) -> bool:
        return self.sdf.distance(x, y) <= 0.0


class Circle(SDFShape):
    """Disk centered at the origin."""

    def __init__(self, radius: float) -> None:
        super().__init__(CircleSDF(radius))
        self.radius = radius


class Rectangle(SDFShape):
    """Axis-aligned rectangle centered at the origin."""

    def __init__(self, half_width: float, half_height: float) -> None:
        super().__init__(RectangleSDF(half_width, half_height))
        self.half_width = half_width
        self.half_height = half_height


class Oval(SDFShape):
    """Axis-aligned ellipse centered at the origin."""

    def __init__(self, radius_x: float, radius_y: float) -> None:
        super().__init__(OvalSDF(radius_x, radius_y))
        self.radius_x = radius_x
        self.radius_y = radius_y


class Infinite(Object):
    """Full-plane geometry of infinite extent; use as a background layer."""

    def sample(self, x: float, y: float) -> tuple[int, int, int, int]:
        return WHITE

    def hit(self, x: float, y: float) -> bool:
        return True
