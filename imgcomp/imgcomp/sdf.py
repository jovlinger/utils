"""Signed distance fields and combinators (negative inside, positive outside)."""

from __future__ import annotations

import math
from typing import Protocol


class SDF(Protocol):
    """Maps center-based local coordinates to signed distance in pixels."""

    def distance(self, x: float, y: float) -> float:
        """Return signed distance: negative inside, zero on boundary, positive outside."""


class CircleSDF:
    """Disk centered at the origin."""

    def __init__(self, radius: float) -> None:
        if radius < 0.0:
            raise ValueError("radius must be non-negative")
        self.radius = radius

    def distance(self, x: float, y: float) -> float:
        return math.hypot(x, y) - self.radius


class RectangleSDF:
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


class OvalSDF:
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


class UnionSDF:
    """Boolean union (minimum distance)."""

    def __init__(self, left: SDF, right: SDF) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        return min(self.left.distance(x, y), self.right.distance(x, y))


class IntersectSDF:
    """Boolean intersection (maximum distance)."""

    def __init__(self, left: SDF, right: SDF) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        return max(self.left.distance(x, y), self.right.distance(x, y))


class SubtractSDF:
    """Boolean subtract: left with right removed."""

    def __init__(self, left: SDF, right: SDF) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        return max(self.left.distance(x, y), -self.right.distance(x, y))


class OffsetSDF:
    """Expand (fatten) or shrink (thin) the boundary along the SDF normal field."""

    def __init__(self, inner: SDF, offset: float) -> None:
        # Positive offset moves the boundary outward (fatten).
        # Negative offset moves it inward (thin).
        self.inner = inner
        self.offset = offset

    def distance(self, x: float, y: float) -> float:
        return self.inner.distance(x, y) - self.offset


class RotateSDF:
    """Rotate query points about the origin before evaluating the inner field."""

    def __init__(self, inner: SDF, degrees: float) -> None:
        self.inner = inner
        self.degrees = degrees
        radians = math.radians(degrees)
        self._cos = math.cos(radians)
        self._sin = math.sin(radians)

    def distance(self, x: float, y: float) -> float:
        local_x = x * self._cos + y * self._sin
        local_y = -x * self._sin + y * self._cos
        return self.inner.distance(local_x, local_y)


class StretchSDF:
    """Non-uniform scale of query points before evaluating the inner field."""

    def __init__(self, inner: SDF, scale_x: float, scale_y: float) -> None:
        if scale_x == 0.0 or scale_y == 0.0:
            raise ValueError("scale_x and scale_y must be non-zero")
        self.inner = inner
        self.scale_x = scale_x
        self.scale_y = scale_y

    def distance(self, x: float, y: float) -> float:
        return self.inner.distance(x / self.scale_x, y / self.scale_y)


def union(left: SDF, right: SDF) -> UnionSDF:
    return UnionSDF(left, right)


def intersect(left: SDF, right: SDF) -> IntersectSDF:
    return IntersectSDF(left, right)


def subtract(left: SDF, right: SDF) -> SubtractSDF:
    return SubtractSDF(left, right)


def fatten(inner: SDF, amount: float) -> OffsetSDF:
    """Move the boundary outward by amount pixels."""
    return OffsetSDF(inner, amount)


def thin(inner: SDF, amount: float) -> OffsetSDF:
    """Move the boundary inward by amount pixels."""
    return OffsetSDF(inner, -amount)


def rotate(inner: SDF, degrees: float) -> RotateSDF:
    return RotateSDF(inner, degrees)


def stretch(inner: SDF, scale_x: float, scale_y: float) -> StretchSDF:
    return StretchSDF(inner, scale_x, scale_y)
