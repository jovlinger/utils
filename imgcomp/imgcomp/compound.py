"""SDF compound geometry (white fill until wrapped in Color)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Optional

from imgcomp.intersect_cache import cached_intersected_by
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.affine import Affine
from imgcomp.shape import AABB, Bounds, Shape, StackLangBody
from imgcomp.shapes import SDFShape, assert_not_stacklang
from imgcomp.stack_type import PrePost, strip_prepost


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


def _union_from_members(
    members: list[Shape],
    *,
    original: Union | None = None,
) -> Optional[Shape]:
    if not members:
        return None
    if original is not None and len(members) == len(original.members) and all(
        culled is member for culled, member in zip(members, original.members)
    ):
        return original
    if len(members) == 1:
        return members[0]
    return Union(*members)


class Union(Shape):
    """Combine members; geometry-only SDFShapes or painted scene objects."""

    def __init__(self, *members: Shape | Sequence[Shape]) -> None:
        self.members = _union_members(*members)

    def distance(self, x: float, y: float) -> float:
        """SDF union (min distance) when every member is SDF geometry."""
        assert_not_stacklang("distance")
        if not all(isinstance(member, SDFShape) for member in self.members):
            raise TypeError("distance() requires SDF geometry members")
        dist = self.members[0].distance(x, y)  # type: ignore[union-attr]
        for member in self.members[1:]:
            dist = min(dist, member.distance(x, y))  # type: ignore[union-attr]
        return dist

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        assert_not_stacklang("color_at")
        accum: RGBA = TRANSPARENT
        for member in reversed(self.members):
            if not (layer := member.color_at(x, y)):
                continue
            accum = src_over(layer, accum)
            if accum[3] >= 255:
                break
        return accum if accum[3] > 0 else None

    def color_at_stacklang(self) -> StackLangBody:
        """Back-to-front src_over of each member's ``color_at_stacklang``."""
        body: StackLangBody = [
            PrePost(
                ["push_transparent_accum"],
                pre=["gy", "gx"],
                post=["gy", "gx", "dr", "dg", "db", "da"],
                label="union_init",
            )
        ]
        for member in reversed(self.members):
            body.append(
                PrePost(
                    [
                        "dup_anchor_xy",
                        *strip_prepost(member.color_at_stacklang()),
                        "drop_hit_xy",
                        "src_over_layer",
                    ],
                    pre=["gy", "gx", "dr", "dg", "db", "da"],
                    post=["gy", "gx", "dr", "dg", "db", "da"],
                    label="union_member",
                )
            )
        return body

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        for member in reversed(self.members):
            if (picked := member.pick_target(x, y)):
                return picked
        return None

    def AABB(self) -> Optional[AABB]:
        return AABB.union(member.AABB() for member in self.members)

    def bounds(self) -> Optional[Bounds]:
        return Bounds.union_envelope(member.bounds() for member in self.members)

    def maybe_intersect_rect(self, rect: AABB) -> bool:
        return any(member.maybe_intersect_rect(rect) for member in self.members)

    def cachekey(self) -> tuple[Any, ...]:
        return ("union", tuple(member.cachekey() for member in self.members))

    def intersected_by(self, rect: AABB) -> Optional[Shape]:
        members = [
            culled
            for member in self.members
            if (culled := cached_intersected_by(member, rect)) is not None
        ]
        return _union_from_members(members, original=self)


class Intersect(SDFShape):
    """Geometric intersection of two SDF shapes."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        assert_not_stacklang("distance")
        return max(self.left.distance(x, y), self.right.distance(x, y))

    def AABB(self) -> Optional[AABB]:
        left = self.left.AABB()
        right = self.right.AABB()
        if left is None or right is None:
            return None
        return left.intersection(right)

    def bounds(self) -> Optional[Bounds]:
        left = self.left.bounds()
        right = self.right.bounds()
        if left is None or right is None:
            return None
        inter = left.to_aabb().intersection(right.to_aabb())
        if inter is None:
            return Bounds.from_aabb(AABB(0.0, 0.0, 0.0, 0.0))
        return Bounds.from_aabb(inter)

    def maybe_intersect_rect(self, rect: AABB) -> bool:
        return self.left.maybe_intersect_rect(rect) and self.right.maybe_intersect_rect(
            rect
        )

    def cachekey(self) -> tuple[Any, ...]:
        return ("intersect", self.left.cachekey(), self.right.cachekey())

    def intersected_by(self, rect: AABB) -> Optional[Shape]:
        left = cached_intersected_by(self.left, rect)
        if left is None:
            return None
        right = cached_intersected_by(self.right, rect)
        if right is None:
            return None
        if left is self.left and right is self.right:
            return self
        return Intersect(left, right)

    def distance_stacklang(self) -> StackLangBody:
        return [
            *self.left.distance_stacklang(),
            "dup_anchor_push_xy",
            *self.right.distance_stacklang(),
            "float_max2",
        ]


class Subtract(SDFShape):
    """Geometric subtract: left with right removed."""

    def __init__(self, left: SDFShape, right: SDFShape) -> None:
        self.left = left
        self.right = right

    def distance(self, x: float, y: float) -> float:
        assert_not_stacklang("distance")
        return max(self.left.distance(x, y), -self.right.distance(x, y))

    def AABB(self) -> Optional[AABB]:
        return self.left.AABB()

    def bounds(self) -> Optional[Bounds]:
        return self.left.bounds()

    def maybe_intersect_rect(self, rect: AABB) -> bool:
        return self.left.maybe_intersect_rect(rect)

    def cachekey(self) -> tuple[Any, ...]:
        return ("subtract", self.left.cachekey(), self.right.cachekey())

    def intersected_by(self, rect: AABB) -> Optional[Shape]:
        left = cached_intersected_by(self.left, rect)
        if left is None:
            return None
        right = cached_intersected_by(self.right, rect)
        if right is None:
            return None
        if left is self.left and right is self.right:
            return self
        return Subtract(left, right)

    def distance_stacklang(self) -> StackLangBody:
        return [
            *self.left.distance_stacklang(),
            "dup_anchor_push_xy",
            *self.right.distance_stacklang(),
            "float_neg",
            "float_max2",
        ]


class Fatten(SDFShape):
    """Expand the boundary outward by amount pixels."""

    def __init__(self, shape: SDFShape, amount: float) -> None:
        self.inner = shape
        self.amount = amount

    def distance(self, x: float, y: float) -> float:
        assert_not_stacklang("distance")
        return self.inner.distance(x, y) - self.amount

    def AABB(self) -> Optional[AABB]:
        child = self.inner.AABB()
        if child is None:
            return None
        return child.expanded(abs(self.amount))

    def bounds(self) -> Optional[Bounds]:
        child = self.inner.bounds()
        if child is None:
            return None
        pad = abs(self.amount)
        return Bounds(child.local.expanded(pad), child.to_parent)

    def cachekey(self) -> tuple[Any, ...]:
        return ("fatten", self.amount, self.inner.cachekey())


class Thin(SDFShape):
    """Move the boundary inward by amount pixels."""

    def __init__(self, shape: SDFShape, amount: float) -> None:
        self.inner = shape
        self.amount = amount

    def distance(self, x: float, y: float) -> float:
        assert_not_stacklang("distance")
        return self.inner.distance(x, y) + self.amount

    def AABB(self) -> Optional[AABB]:
        return self.inner.AABB()

    def bounds(self) -> Optional[Bounds]:
        return self.inner.bounds()

    def cachekey(self) -> tuple[Any, ...]:
        return ("thin", self.amount, self.inner.cachekey())


class RotateShape(SDFShape):
    """Rotate an SDF shape about the local origin."""

    def __init__(self, shape: SDFShape, degrees: float) -> None:
        self.inner = shape
        self.degrees = degrees
        radians = math.radians(degrees)
        self._cos = math.cos(radians)
        self._sin = math.sin(radians)

    def distance(self, x: float, y: float) -> float:
        assert_not_stacklang("distance")
        local_x = x * self._cos + y * self._sin
        local_y = -x * self._sin + y * self._cos
        return self.inner.distance(local_x, local_y)

    def AABB(self) -> Optional[AABB]:
        child = self.inner.AABB()
        if child is None:
            return None
        return child.rotated(self.degrees)

    def bounds(self) -> Optional[Bounds]:
        child = self.inner.bounds()
        if child is None:
            return None
        return child.transformed(Affine.rotate(self.degrees))

    def cachekey(self) -> tuple[Any, ...]:
        return ("rotate_shape", self.degrees, self.inner.cachekey())


class StretchShape(SDFShape):
    """Non-uniform scale of an SDF shape about the local origin."""

    def __init__(self, shape: SDFShape, scale_x: float, scale_y: float) -> None:
        if scale_x == 0.0 or scale_y == 0.0:
            raise ValueError("scale_x and scale_y must be non-zero")
        self.inner = shape
        self.scale_x = scale_x
        self.scale_y = scale_y

    def distance(self, x: float, y: float) -> float:
        assert_not_stacklang("distance")
        return self.inner.distance(x / self.scale_x, y / self.scale_y)

    def AABB(self) -> Optional[AABB]:
        child = self.inner.AABB()
        if child is None:
            return None
        return child.stretched(self.scale_x, self.scale_y)

    def bounds(self) -> Optional[Bounds]:
        child = self.inner.bounds()
        if child is None:
            return None
        return child.transformed(Affine.stretch(self.scale_x, self.scale_y))

    def cachekey(self) -> tuple[Any, ...]:
        return ("stretch_shape", self.scale_x, self.scale_y, self.inner.cachekey())
