"""Layer cache for per-top-level-object raster reuse."""

from __future__ import annotations

from typing import Dict, Hashable, List, Tuple

from imgcomp.content_key import content_key
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import Shape
from imgcomp.surface import ArraySurface, Surface


class LayerCache:
    """Cache full-viewport rasters of individual scene-list entries."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        self.width = width
        self.height = height
        self._layers: Dict[Tuple[Hashable, ...], ArraySurface] = {}
        self.hits: int = 0
        self.misses: int = 0

    def clear(self) -> None:
        self._layers.clear()
        self.hits = 0
        self.misses = 0

    def resize(self, width: int, height: int) -> None:
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        self.clear()

    def rasterize_shape(self, obj: Shape) -> ArraySurface:
        """Paint one object alone into a transparent viewport-sized surface."""
        surface = ArraySurface(self.width, self.height)
        for y in range(self.height):
            for x in range(self.width):
                local_x = x + 0.5 - self.width / 2.0
                local_y = y + 0.5 - self.height / 2.0
                color = obj.color_at(local_x, local_y)
                if color is not None:
                    surface.set_pixel(x, y, color)
        return surface

    def layer_surface(self, obj: Shape) -> ArraySurface:
        key = content_key(obj)
        cached = self._layers.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        surface = self.rasterize_shape(obj)
        self._layers[key] = surface
        self.misses += 1
        return surface

    def render(self, root: Scene) -> Surface:
        """Composite scene list using cached per-layer rasters (back to front)."""
        layers = as_z_list(root)
        out = ArraySurface(self.width, self.height)
        layer_surfaces: List[ArraySurface] = [self.layer_surface(obj) for obj in layers]
        # Match NaiveCompositor: closest-to-furthest with src_over(layer, accum).
        for y in range(self.height):
            for x in range(self.width):
                accum: RGBA = TRANSPARENT
                for layer in reversed(layer_surfaces):
                    pixel = layer.get_pixel(x, y)
                    if pixel[3] <= 0:
                        continue
                    accum = src_over(pixel, accum)
                    if accum[3] >= 255:
                        break
                out.set_pixel(x, y, accum)
        return out

    def stats(self) -> Dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self._layers),
        }
