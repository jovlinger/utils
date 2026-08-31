"""Scene shape ABC."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from imgcomp.affine import Affine
from imgcomp.rgba import RGBA

StackLangBody = list[Any]


@dataclass(frozen=True)
class AABB:
    """Axis-aligned bounds in local center-based coordinates."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    @classmethod
    def from_rect(cls, x0: float, y0: float, x1: float, y1: float) -> AABB:
        return cls(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    @classmethod
    def union(cls, boxes: Iterable[Optional[AABB]]) -> Optional[AABB]:
        xmin = ymin = math.inf
        xmax = ymax = -math.inf
        saw_box = False
        for box in boxes:
            if box is None:
                return None
            saw_box = True
            xmin = min(xmin, box.xmin)
            ymin = min(ymin, box.ymin)
            xmax = max(xmax, box.xmax)
            ymax = max(ymax, box.ymax)
        if not saw_box:
            return None
        return cls(xmin, ymin, xmax, ymax)

    def intersects(self, other: AABB) -> bool:
        return not (
            self.xmax < other.xmin
            or other.xmax < self.xmin
            or self.ymax < other.ymin
            or other.ymax < self.ymin
        )

    def intersection(self, other: AABB) -> Optional[AABB]:
        xmin = max(self.xmin, other.xmin)
        ymin = max(self.ymin, other.ymin)
        xmax = min(self.xmax, other.xmax)
        ymax = min(self.ymax, other.ymax)
        if xmax < xmin or ymax < ymin:
            return None
        return AABB(xmin, ymin, xmax, ymax)

    def translated(self, tx: float, ty: float) -> AABB:
        return AABB(self.xmin + tx, self.ymin + ty, self.xmax + tx, self.ymax + ty)

    def rotated(self, degrees: float) -> AABB:
        cos_a = math.cos(math.radians(degrees))
        sin_a = math.sin(math.radians(degrees))
        corners = (
            (self.xmin, self.ymin),
            (self.xmin, self.ymax),
            (self.xmax, self.ymin),
            (self.xmax, self.ymax),
        )
        xs: list[float] = []
        ys: list[float] = []
        for x, y in corners:
            xs.append(x * cos_a - y * sin_a)
            ys.append(x * sin_a + y * cos_a)
        return AABB(min(xs), min(ys), max(xs), max(ys))

    def stretched(self, scale_x: float, scale_y: float) -> AABB:
        xs = (self.xmin * scale_x, self.xmax * scale_x)
        ys = (self.ymin * scale_y, self.ymax * scale_y)
        return AABB(min(xs), min(ys), max(xs), max(ys))

    def expanded(self, pad: float) -> AABB:
        return AABB(self.xmin - pad, self.ymin - pad, self.xmax + pad, self.ymax + pad)

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (self.xmin, self.ymin, self.xmax, self.ymax)


@dataclass(frozen=True)
class Bounds:
    """Local AABB carried through an affine into parent space (may be oriented)."""

    local: AABB
    to_parent: Affine = field(default_factory=Affine.identity)

    @classmethod
    def from_aabb(cls, box: AABB) -> Bounds:
        return cls(local=box)

    @classmethod
    def union_envelope(cls, boxes: Iterable[Optional[Bounds]]) -> Optional[Bounds]:
        """Axis-aligned envelope of several bounds (conservative, loses orientation)."""
        aabbs: list[AABB] = []
        for box in boxes:
            if box is None:
                return None
            aabbs.append(box.to_aabb())
        if not aabbs:
            return None
        merged = AABB.union(aabbs)
        if merged is None:
            return None
        return cls.from_aabb(merged)

    def to_aabb(self) -> AABB:
        """Conservative axis-aligned envelope in parent space."""
        return self.to_parent.transform_aabb(self.local)

    def transformed(self, aff: Affine) -> Bounds:
        return Bounds(local=self.local, to_parent=aff @ self.to_parent)

    def intersects_aabb(self, rect: AABB) -> bool:
        """Conservative test against an axis-aligned query rect in parent space."""
        if self.to_parent.is_identity():
            return self.local.intersects(rect)
        query_local = self.to_parent.inverse().transform_aabb(rect)
        return self.local.intersects(query_local)


class Shape(ABC):
    """Maps center-based local pixel coordinates to color (None = miss)."""

    @abstractmethod
    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        """Return straight RGBA when (x, y) hits, else None."""

    @abstractmethod
    def AABB(self) -> Optional[AABB]:
        """Conservative local axis-aligned bounds, or None when unbounded."""

    def bounds(self) -> Optional[Bounds]:
        """Conservative bounds in local space, possibly oriented via affine."""
        box = self.AABB()
        if box is None:
            return None
        return Bounds.from_aabb(box)

    def affect(self) -> Affine:
        """Local affine for this node: identity unless a wrapper overrides."""
        return Affine.identity()

    def maybe_intersect_rect(self, rect: AABB) -> bool:
        bounds = self.bounds()
        if bounds is None:
            return True
        return bounds.intersects_aabb(rect)

    def pick_target(self, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
        """Return the leaf shape and its local coords when (x, y) hits."""
        if not self.color_at(x, y):
            return None
        return self, x, y

    def translate(self, tx: float, ty: float) -> Shape:
        """Return a new shape translated to (tx, ty); does not modify self."""
        from imgcomp.wrappers import Translate

        return Translate(self, tx, ty)

    def rotate(self, degrees: float) -> Shape:
        """Return a new shape rotated about the origin; does not modify self."""
        from imgcomp.wrappers import Rotate

        return Rotate(self, degrees)

    def stretch(self, scale_x: float, scale_y: float) -> Shape:
        """Return a new shape scaled about the origin; does not modify self."""
        from imgcomp.wrappers import Stretch

        return Stretch(self, scale_x, scale_y)

    def color(self, color: RGBA) -> Shape:
        """Return a new shape filled with color; does not modify self."""
        from imgcomp.wrappers import Color

        return Color(self, color)

    def color_mod(
        self,
        *,
        r_mul: float = 1.0,
        g_mul: float = 1.0,
        b_mul: float = 1.0,
        a_mul: float = 1.0,
    ) -> Shape:
        """Return a new shape with channel multipliers; does not modify self."""
        from imgcomp.wrappers import ColorMod

        return ColorMod(self, r_mul=r_mul, g_mul=g_mul, b_mul=b_mul, a_mul=a_mul)

    def union(self, *others: Shape) -> Shape:
        """Return a new shape combining self and others; does not modify self."""
        from imgcomp.compound import Union

        return Union(self, *others)

    def subtract(self, other: Shape) -> Shape:
        """Return a new shape with other removed; does not modify self."""
        from imgcomp.compound import Subtract
        from imgcomp.shapes import SDFShape

        if not isinstance(self, SDFShape) or not isinstance(other, SDFShape):
            raise TypeError("subtract requires SDF geometry operands")
        return Subtract(self, other)

    def intersect(self, other: Shape) -> Shape:
        """Return a new shape keeping overlap only; does not modify self."""
        from imgcomp.compound import Intersect
        from imgcomp.shapes import SDFShape

        if not isinstance(self, SDFShape) or not isinstance(other, SDFShape):
            raise TypeError("intersect requires SDF geometry operands")
        return Intersect(self, other)

    def fatten(self, amount: float) -> Shape:
        """Return a new shape expanded outward; does not modify self."""
        from imgcomp.compound import Fatten
        from imgcomp.shapes import SDFShape

        if not isinstance(self, SDFShape):
            raise TypeError("fatten requires SDF geometry")
        return Fatten(self, amount)

    def thin(self, amount: float) -> Shape:
        """Return a new shape shrunk inward; does not modify self."""
        from imgcomp.compound import Thin
        from imgcomp.shapes import SDFShape

        if not isinstance(self, SDFShape):
            raise TypeError("thin requires SDF geometry")
        return Thin(self, amount)

    def rotate_shape(self, degrees: float) -> Shape:
        """Return a new SDF shape rotated in field space; does not modify self."""
        from imgcomp.compound import RotateShape
        from imgcomp.shapes import SDFShape

        if not isinstance(self, SDFShape):
            raise TypeError("rotate_shape requires SDF geometry")
        return RotateShape(self, degrees)

    def stretch_shape(self, scale_x: float, scale_y: float) -> Shape:
        """Return a new SDF shape scaled in field space; does not modify self."""
        from imgcomp.compound import StretchShape
        from imgcomp.shapes import SDFShape

        if not isinstance(self, SDFShape):
            raise TypeError("stretch_shape requires SDF geometry")
        return StretchShape(self, scale_x, scale_y)

    def on_touch(self, x: float, y: float) -> None:
        """Handle a touch/click at local coordinates."""

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        """Handle a drag at local coordinates."""

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        """Handle a scroll wheel tick at local coordinates."""

    def color_at_stacklang(self) -> StackLangBody:
        """Stacklang with gx gy on stack; leaves gx gy r g b a (or transparent miss).

        Default falls back to ``call_python_method`` on ``color_at``. SDF shapes
        override via ``distance_stacklang`` composition.
        """
        return ["call_python_method", "color_at"]
