"""Loaded leaf objects (non-SDF)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Sequence

from imgcomp.shape import Shape
from imgcomp.rgba import RGBA
from imgcomp.surface import ArraySurface


class ImageObject(Shape):
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

    def color_at(self, x: float, y: float) -> Optional[RGBA]:
        """Return straight RGBA at the texel, or None on miss / transparent."""
        half_w = self._surface.width / 2.0
        half_h = self._surface.height / 2.0
        tx = int(math.floor(x + half_w))
        ty = int(math.floor(y + half_h))
        if tx < 0 or ty < 0 or tx >= self._surface.width or ty >= self._surface.height:
            return None
        color = self._surface.get_pixel(tx, ty)
        if color[3] <= 0:
            return None
        return color
