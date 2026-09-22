"""2D affine maps between local and global center-based coordinates."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class Affine:
    """Maps local -> global: [x'] = [a b tx] [x]
                             [y']   [c d ty] [y]
                                             [1]

    Pure-Python reference API. Hot render paths should call ``imgcomp._math``
    cdef kernels (``affine_mat_mul``, ``affine_mat_vec_xy``,
    ``affine_mat_vec_batch``) from Cython without per-point Python overhead.
    """

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    tx: float = 0.0
    ty: float = 0.0

    @staticmethod
    def identity() -> "Affine":
        return Affine()

    @staticmethod
    def translate(tx: float, ty: float) -> "Affine":
        return Affine(tx=tx, ty=ty)

    @staticmethod
    def rotate(degrees: float) -> "Affine":
        """Rotate local coords about the origin (+y down, matches former Rotate)."""
        rad = math.radians(degrees)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        return Affine(a=cos_a, b=-sin_a, c=sin_a, d=cos_a)

    @staticmethod
    def stretch(scale_x: float, scale_y: float) -> "Affine":
        if scale_x == 0.0 or scale_y == 0.0:
            raise ValueError("scale_x and scale_y must be non-zero")
        return Affine(a=scale_x, d=scale_y)

    def __matmul__(self, other: "Affine") -> "Affine":
        """Compose: (self @ other) applies other first, then self (local->global)."""
        return Affine(
            a=self.a * other.a + self.b * other.c,
            b=self.a * other.b + self.b * other.d,
            c=self.c * other.a + self.d * other.c,
            d=self.c * other.b + self.d * other.d,
            tx=self.a * other.tx + self.b * other.ty + self.tx,
            ty=self.c * other.tx + self.d * other.ty + self.ty,
        )

    def transform(self, x: float, y: float) -> Point:
        """matXvec: local ``(x, y)`` -> global."""
        return (
            self.a * x + self.b * y + self.tx,
            self.c * x + self.d * y + self.ty,
        )

    def inverse(self) -> "Affine":
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1e-12:
            raise ValueError("affine is not invertible")
        inv_det = 1.0 / det
        ia = self.d * inv_det
        ib = -self.b * inv_det
        ic = -self.c * inv_det
        id_ = self.a * inv_det
        return Affine(
            a=ia,
            b=ib,
            c=ic,
            d=id_,
            tx=-(ia * self.tx + ib * self.ty),
            ty=-(ic * self.tx + id_ * self.ty),
        )

    def to_local(self, gx: float, gy: float) -> Point:
        """Map global -> local via inverse."""
        return self.inverse().transform(gx, gy)

    def is_identity(self, *, eps: float = 1e-12) -> bool:
        return (
            abs(self.a - 1.0) < eps
            and abs(self.b) < eps
            and abs(self.c) < eps
            and abs(self.d - 1.0) < eps
            and abs(self.tx) < eps
            and abs(self.ty) < eps
        )

    def as_key(self) -> Tuple[float, float, float, float, float, float]:
        return (self.a, self.b, self.c, self.d, self.tx, self.ty)
