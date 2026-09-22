"""SDF compound geometry (white fill until wrapped in Color)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Optional

from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.shape import Shape
from imgcomp.shapes import SDFShape


def _union_members(*args: Shape | Sequence[Shape]) -> tuple[Shape, ...]:
    if len(args) == 1 and isinstance(args[0], (list, tuple)):
        members = tuple(args[0])
    else:
        members = args  # type: ignore[assignment]
    if not members:
        raise ValueError("Union requires at least one member")
    for member in members:
        if not isinstance(member, Shape):
            raise TypeError("Union members must be Shape instances")
    return members


class Union(Shape):
    """Combine members; geometry-only SDFShapes or painted scene objects."""

    def __init__(self, *members: Shape | Sequence[Shape]) -> None:
        self.members = _union_members(*members)

    def distance(self, x: float, y: float) -> float:
        """SDF union (min distance) when every member is SDF geometry."""
        if not all(isinstance(member, SDFShape) for member in self.members):
            raise TypeError("distance() requires SDF geometry members")
        dist = self.members[0].distance(x, y)  # type: ignore[union-attr]
        for member in self.members[1:]:
            dist = min(dist, member.distance(x, y))  # type: ignore[union-attr]
        return dist

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        accum: RGBA = TRANSPARENT
        for member in reversed(self.members):
            if not (layer := member.color_at(x, y)):
                continue
            accum = src_over(layer, accum)
            if accum[3] >= 255:
                break
        return accum if accum[3] > 0 else None

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        for member in reversed(self.members):
            if (picked := member.pick_target(x, y)):
                return picked
        return None


class Intersect(SDFShape):
    """Geometric intersection of two SDF shapes."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        return max(self.left.distance(x, y), self.right.distance(x, y))


class Subtract(SDFShape):
    """Geometric subtract: left with right removed."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        return max(self.left.distance(x, y), -self.right.distance(x, y))


class Fatten(SDFShape):
    """Expand the boundary outward by amount pixels."""

    def __init__(self, shape: SDFShape, amount: float) -> None:
        self.inner = shape
        self.amount = amount

    def distance(self, x: float, y: float) -> float:
        return self.inner.distance(x, y) - self.amount


class Thin(SDFShape):
    """Move the boundary inward by amount pixels."""

    def __init__(self, shape: SDFShape, amount: float) -> None:
        self.inner = shape
        self.amount = amount

    def distance(self, x: float, y: float) -> float:
        return self.inner.distance(x, y) + self.amount


class RotateShape(SDFShape):
    """Rotate an SDF shape about the local origin."""

    def __init__(self, shape: SDFShape, degrees: float) -> None:
        self.inner = shape
        self.degrees = degrees
        radians = math.radians(degrees)
        self._cos = math.cos(radians)
        self._sin = math.sin(radians)

    def distance(self, x: float, y: float) -> float:
        local_x = x * self._cos + y * self._sin
        local_y = -x * self._sin + y * self._cos
        return self.inner.distance(local_x, local_y)


class StretchShape(SDFShape):
    """Non-uniform scale of an SDF shape about the local origin."""

    def __init__(self, shape: SDFShape, scale_x: float, scale_y: float) -> None:
        if scale_x == 0.0 or scale_y == 0.0:
            raise ValueError("scale_x and scale_y must be non-zero")
        self.inner = shape
        self.scale_x = scale_x
        self.scale_y = scale_y

    def distance(self, x: float, y: float) -> float:
        return self.inner.distance(x / self.scale_x, y / self.scale_y)


def union(*members: Shape | Sequence[Shape]) -> Union:
    return Union(*members)


def intersect(left: SDFShape, right: SDFShape) -> Intersect:
    return Intersect(left, right)


def subtract(left: SDFShape, right: SDFShape) -> Subtract:
    return Subtract(left, right)


def fatten(shape: SDFShape, amount: float) -> Fatten:
    return Fatten(shape, amount)


def thin(shape: SDFShape, amount: float) -> Thin:
    return Thin(shape, amount)


def rotate(shape: SDFShape, degrees: float) -> RotateShape:
    return RotateShape(shape, degrees)


def stretch(shape: SDFShape, scale_x: float, scale_y: float) -> StretchShape:
    return StretchShape(shape, scale_x, scale_y)
