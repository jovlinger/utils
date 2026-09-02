"""Scene shape ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from imgcomp.rgba import RGBA


class Shape(ABC):
    """Maps center-based local pixel coordinates to color (None = miss)."""

    @abstractmethod
    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        """Return straight RGBA when (x, y) hits, else None."""

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
