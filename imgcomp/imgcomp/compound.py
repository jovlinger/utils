"""SDF compound geometry (white fill until wrapped in Color)."""

from __future__ import annotations

from imgcomp.shapes import SDFShape
from imgcomp.sdf import (
    IntersectSDF,
    SubtractSDF,
    UnionSDF,
    fatten as fatten_sdf,
    rotate as rotate_sdf,
    stretch as stretch_sdf,
    thin as thin_sdf,
)


class Union(SDFShape):
    """Geometric union of two SDF shapes."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        super().__init__(UnionSDF(left.sdf, right.sdf))
        self.left = left
        self.right = right


class Intersect(SDFShape):
    """Geometric intersection of two SDF shapes."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        super().__init__(IntersectSDF(left.sdf, right.sdf))
        self.left = left
        self.right = right


class Subtract(SDFShape):
    """Geometric subtract: left with right removed."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        super().__init__(SubtractSDF(left.sdf, right.sdf))
        self.left = left
        self.right = right


class Fatten(SDFShape):
    """Expand the boundary outward by amount pixels."""

    def __init__(self, shape: SDFShape, amount: float) -> None:
        super().__init__(fatten_sdf(shape.sdf, amount))
        self.inner = shape
        self.amount = amount


class Thin(SDFShape):
    """Move the boundary inward by amount pixels."""

    def __init__(self, shape: SDFShape, amount: float) -> None:
        super().__init__(thin_sdf(shape.sdf, amount))
        self.inner = shape
        self.amount = amount


class RotateShape(SDFShape):
    """Rotate an SDF shape about the local origin."""

    def __init__(self, shape: SDFShape, degrees: float) -> None:
        super().__init__(rotate_sdf(shape.sdf, degrees))
        self.inner = shape
        self.degrees = degrees


class StretchShape(SDFShape):
    """Non-uniform scale of an SDF shape about the local origin."""

    def __init__(self, shape: SDFShape, scale_x: float, scale_y: float) -> None:
        super().__init__(stretch_sdf(shape.sdf, scale_x, scale_y))
        self.inner = shape
        self.scale_x = scale_x
        self.scale_y = scale_y


def union(left: SDFShape, right: SDFShape) -> Union:
    return Union(left, right)


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
