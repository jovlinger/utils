"""Surface ABC and a CPU byte-buffer implementation (no numpy)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from array import array
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence

from imgcomp.rgba import RGBA, TRANSPARENT


class Surface(ABC):
    """Mutable RGBA raster. Implementations must not require numpy."""

    @property
    @abstractmethod
    def width(self) -> int:
        """Pixel width."""

    @property
    @abstractmethod
    def height(self) -> int:
        """Pixel height."""

    @abstractmethod
    def get_pixel(self, x: int, y: int) -> RGBA:
        """Read one pixel."""

    @abstractmethod
    def set_pixel(self, x: int, y: int, color: RGBA) -> None:
        """Write one pixel."""

    @abstractmethod
    def fill(self, color: RGBA) -> None:
        """Fill the entire surface."""

    def iter_pixels(self) -> Iterator[tuple[int, int, RGBA]]:
        """Yield (x, y, color) for every pixel."""
        for y in range(self.height):
            for x in range(self.width):
                yield x, y, self.get_pixel(x, y)

    def rgba_bytes(self) -> bytes:
        """Return raw RGBA bytes (row-major, top row first)."""
        if hasattr(self, "to_bytes"):
            return self.to_bytes()  # type: ignore[attr-defined]
        rows = bytearray()
        for _x, _y, color in self.iter_pixels():
            rows.extend(color)
        return bytes(rows)

    def write_png(self, path: Path | str) -> None:
        """Write this straight RGBA surface to PNG."""
        from PIL import Image

        image = Image.frombytes("RGBA", (self.width, self.height), self.rgba_bytes())
        image.save(path)


class ArraySurface(Surface):
    """RGBA surface backed by array.array('B') -- four bytes per pixel."""

    def __init__(self, width: int, height: int, *, fill: RGBA = TRANSPARENT) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        self._width = width
        self._height = height
        self._data: array[int] = array("B", [0]) * (width * height * 4)
        self.fill(fill)

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def _offset(self, x: int, y: int) -> int:
        if x < 0 or y < 0 or x >= self._width or y >= self._height:
            raise IndexError(f"pixel out of bounds: ({x}, {y})")
        return (y * self._width + x) * 4

    def get_pixel(self, x: int, y: int) -> RGBA:
        offset = self._offset(x, y)
        return (
            self._data[offset],
            self._data[offset + 1],
            self._data[offset + 2],
            self._data[offset + 3],
        )

    def set_pixel(self, x: int, y: int, color: RGBA) -> None:
        offset = self._offset(x, y)
        self._data[offset : offset + 4] = array("B", color)

    def fill(self, color: RGBA) -> None:
        red, green, blue, alpha = color
        row = array("B", [red, green, blue, alpha]) * self._width
        packed = array("B")
        for _ in range(self._height):
            packed.extend(row)
        self._data = packed

    def to_bytes(self) -> bytes:
        """Return raw RGBA bytes (row-major)."""
        return self._data.tobytes()

    @classmethod
    def from_rows(cls, rows: Sequence[Sequence[RGBA]]) -> "ArraySurface":
        """Build a surface from nested RGBA rows (top row first)."""
        height = len(rows)
        if height == 0:
            raise ValueError("rows must not be empty")
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("every row must have the same width")
        surface = cls(width, height)
        for y, row in enumerate(rows):
            for x, color in enumerate(row):
                surface.set_pixel(x, y, color)
        return surface


def rows_from_sequence(flat: Sequence[RGBA], width: int, height: int) -> List[List[RGBA]]:
    """Split a flat RGBA sequence into row lists."""
    if len(flat) != width * height:
        raise ValueError("flat sequence length must equal width * height")
    rows: List[List[RGBA]] = []
    index = 0
    for _ in range(height):
        rows.append(list(flat[index : index + width]))
        index += width
    return rows
