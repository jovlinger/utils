"""SDF compound geometry (white fill until wrapped in Color)."""

from __future__ import annotations

from collections.abc import Sequence

from imgcomp.shape import Shape
from imgcomp.sdf import (
    IntersectSDF,
    SDF,
    SubtractSDF,
    UnionSDF,
    fatten as fatten_sdf,
    rotate as rotate_sdf,
    stretch as stretch_sdf,
    thin as thin_sdf,
)
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


def _union_sdf(shapes: Sequence[SDFShape]) -> SDF:
    sdf = shapes[0].sdf
    for shape in shapes[1:]:
        sdf = UnionSDF(sdf, shape.sdf)
    return sdf


class Union(Shape):
    """Combine members; geometry-only SDFShapes or painted scene objects."""

    def __init__(self, *members: Shape | Sequence[Shape]) -> None:
        self.members = _union_members(*members)
        if all(isinstance(member, SDFShape) for member in self.members):
            self.sdf = _union_sdf(self.members)  # type: ignore[arg-type]
        else:
            self.sdf = None

    def sample(self, x: float, y: float) -> tuple[int, int, int, int]:
        raise NotImplementedError("Union geometry is resolved by imgcomp.probe")

    def hit(self, x: float, y: float) -> bool:
        raise NotImplementedError("Union geometry is resolved by imgcomp.probe")


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
