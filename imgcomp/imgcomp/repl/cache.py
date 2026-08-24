"""Layer cache for per-top-level-object raster reuse."""

from __future__ import annotations

from typing import Dict, Hashable, List, Optional, Tuple

from imgcomp.object import Object
from imgcomp.probe import hit_color
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shapes import Circle, Infinite, Oval, Rectangle, SDFShape
from imgcomp.surface import ArraySurface, Surface
from imgcomp.wrappers import Color, ColorMod, Rotate, Stretch, Translate


def content_key(obj: Object) -> Tuple[Hashable, ...]:
    """Structural key for cache identity (parameters that affect pixels)."""
    if isinstance(obj, Translate):
        return ("translate", obj.tx, obj.ty, content_key(obj.child))
    if isinstance(obj, Rotate):
        return ("rotate", obj.degrees, content_key(obj.child))
    if isinstance(obj, Stretch):
        return ("stretch", obj.scale_x, obj.scale_y, content_key(obj.child))
    if isinstance(obj, Color):
        return ("color", obj.color, content_key(obj.child))
    if isinstance(obj, ColorMod):
        return (
            "colormod",
            obj.r_mul,
            obj.g_mul,
            obj.b_mul,
            obj.a_mul,
            content_key(obj.child),
        )
    if isinstance(obj, Circle):
        return ("circle", obj.radius)
    if isinstance(obj, Rectangle):
        return ("rect", obj.half_width, obj.half_height)
    if isinstance(obj, Oval):
        return ("oval", obj.radius_x, obj.radius_y)
    if isinstance(obj, Infinite):
        return ("infinite",)
    if isinstance(obj, SDFShape):
        return ("sdfshape", id(obj.sdf), type(obj).__name__)
    return ("object", type(obj).__name__, id(obj))


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

    def rasterize_object(self, obj: Object) -> ArraySurface:
        """Paint one object alone into a transparent viewport-sized surface."""
        surface = ArraySurface(self.width, self.height)
        for y in range(self.height):
            for x in range(self.width):
                local_x = x + 0.5 - self.width / 2.0
                local_y = y + 0.5 - self.height / 2.0
                color = hit_color(obj, local_x, local_y)
                if color is not None:
                    surface.set_pixel(x, y, color)
        return surface

    def layer_surface(self, obj: Object) -> ArraySurface:
        key = content_key(obj)
        cached = self._layers.get(key)
        if cached is not None:
            self.hits += 1
            return cached
        surface = self.rasterize_object(obj)
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
