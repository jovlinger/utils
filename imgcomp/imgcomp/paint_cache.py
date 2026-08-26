"""Polymorphic paint specialization cache (Hölzle-style PIC at the C boundary).

Call site: paint a region for a z-list. Miss: Python flattens into a typed IR
and stores it under a structural content key. Hit: stay in the Cython paint
kernel for the whole fill. Unflattenable scenes cache None and keep the
Python spine forever for that key.
"""

from __future__ import annotations

from array import array
from typing import Dict, Hashable, Optional, Sequence, Tuple

from imgcomp.content_key import content_key
from imgcomp.flatten import FlatScene, try_flatten
from imgcomp.shape import Shape
from imgcomp.surface import ArraySurface

try:
    from imgcomp import _paint as _native
except ImportError:  # pragma: no cover
    _native = None

SpecializationKey = Tuple[Hashable, ...]


class PaintSpecializationCache:
    """Cache Flattened typed paint IRs keyed by structural z-list identity."""

    def __init__(self) -> None:
        self._entries: Dict[SpecializationKey, Optional[FlatScene]] = {}
        self.hits: int = 0
        self.misses: int = 0

    def clear(self) -> None:
        self._entries.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> Dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self._entries),
        }

    def specialize(self, layers: Sequence[Shape]) -> Optional[FlatScene]:
        """Return cached FlatScene, or None when unflattenable / no extension."""
        if _native is None:
            return None
        key: SpecializationKey = tuple(content_key(obj) for obj in layers)
        if key in self._entries:
            self.hits += 1
            return self._entries[key]
        self.misses += 1
        flat = try_flatten(layers)
        self._entries[key] = flat
        return flat


def paint_extension_available() -> bool:
    """Return True when the Cython paint kernel is importable."""
    return _native is not None


def paint_flat_into_surface(
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    flat: FlatScene,
    surface: ArraySurface,
) -> None:
    if _native is None:
        raise RuntimeError("imgcomp._paint extension is not built")
    _native.rasterize_into(
        width,
        height,
        x0,
        y0,
        x1,
        y1,
        flat.kinds,
        flat.params,
        flat.colors,
        flat.layer_starts,
        flat.layer_ends,
        surface.pixel_buffer(),
        False,
    )


def paint_flat_into_buffer(
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    flat: FlatScene,
    buffer: array[int],
) -> None:
    if _native is None:
        raise RuntimeError("imgcomp._paint extension is not built")
    _native.rasterize_into(
        width,
        height,
        x0,
        y0,
        x1,
        y1,
        flat.kinds,
        flat.params,
        flat.colors,
        flat.layer_starts,
        flat.layer_ends,
        buffer,
        True,
    )


def try_paint_layers(
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    layers: Sequence[Shape],
    surface: ArraySurface,
    cache: PaintSpecializationCache,
) -> bool:
    """Specialize (PIC miss/hit) and paint into surface; False => Python path."""
    flat = cache.specialize(layers)
    if flat is None:
        return False
    paint_flat_into_surface(width, height, x0, y0, x1, y1, flat, surface)
    return True


def try_paint_layers_to_buffer(
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    layers: Sequence[Shape],
    buffer: array[int],
    cache: PaintSpecializationCache,
) -> bool:
    """Specialize and paint into a tile buffer; False => Python path."""
    flat = cache.specialize(layers)
    if flat is None:
        return False
    paint_flat_into_buffer(width, height, x0, y0, x1, y1, flat, buffer)
    return True
