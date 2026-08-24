"""Computed and loaded leaf objects."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

from imgcomp.object import Object
from imgcomp.rgba import RGBA, TRANSPARENT
from imgcomp.surface import ArraySurface


class Circle(Object):
    """Filled disk in local space; optional larger hit radius."""

    def __init__(
        self,
        radius: float,
        color: RGBA,
        *,
        hit_radius: float | None = None,
    ) -> None:
        if radius < 0.0:
            raise ValueError("radius must be non-negative")
        self.radius = radius
        self.color = color
        self.hit_radius = radius if hit_radius is None else hit_radius

    def sample(self, x: float, y: float) -> RGBA:
        if math.hypot(x, y) <= self.radius:
            return self.color
        return TRANSPARENT

    def hit(self, x: float, y: float) -> bool:
        return math.hypot(x, y) <= self.hit_radius


class ImageObject(Object):
    """Bitmap sampled in center-based local coordinates."""

    def __init__(self, surface: ArraySurface) -> None:
        self._surface = surface

    @property
    def width(self) -> int:
        return self._surface.width

    @property
    def height(self) -> int:
        return self._surface.height

    @classmethod
    def from_rgba_rows(cls, rows: Sequence[Sequence[RGBA]]) -> "ImageObject":
        """Build from nested RGBA rows (top row first)."""
        return cls(ArraySurface.from_rows(rows))

    @classmethod
    def load(cls, path: Path | str) -> "ImageObject":
        """Load an image file via Pillow into straight RGBA."""
        from PIL import Image

        image = Image.open(path).convert("RGBA")
        width, height = image.size
        pixels = list(image.getdata())
        rows: list[list[RGBA]] = []
        index = 0
        for _ in range(height):
            row: list[RGBA] = []
            for _ in range(width):
                row.append(pixels[index])  # type: ignore[arg-type]
                index += 1
            rows.append(row)
        return cls.from_rgba_rows(rows)

    def sample(self, x: float, y: float) -> RGBA:
        half_w = self._surface.width / 2.0
        half_h = self._surface.height / 2.0
        tx = int(math.floor(x + half_w))
        ty = int(math.floor(y + half_h))
        if tx < 0 or ty < 0 or tx >= self._surface.width or ty >= self._surface.height:
            return TRANSPARENT
        return self._surface.get_pixel(tx, ty)

    def hit(self, x: float, y: float) -> bool:
        half_w = self._surface.width / 2.0
        half_h = self._surface.height / 2.0
        return abs(x) <= half_w and abs(y) <= half_h
