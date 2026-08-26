"""Pure-Python per-pixel compositor with optional quadtree tile cache."""

from __future__ import annotations

from typing import Optional, Sequence

from imgcomp.compositor import Compositor, PickResult
from imgcomp.paint_cache import PaintSpecializationCache, try_paint_layers
from imgcomp.quad_cache import QuadCache
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import Shape
from imgcomp.surface import ArraySurface, Surface


class NaiveCompositor(Compositor):
    """For each viewport pixel, walk the z-list and accumulate hit colors.

    Pass ``cache=True`` to memoize leaf tiles by structural z-list keys. Cache
    is off by default: single-shot renders do not benefit; animation does.

    Paint specialization (PIC): on first paint of a flattenable scene, Python
    builds a typed IR; later paints with the same content key stay in Cython.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        cache: bool = False,
        cache_tile: int = 16,
    ) -> None:
        super().__init__(width, height)
        self._paint_cache = PaintSpecializationCache()
        self._quad_cache: Optional[QuadCache] = (
            QuadCache(width, height, min_tile=cache_tile, paint_cache=self._paint_cache)
            if cache
            else None
        )

    @property
    def cache(self) -> Optional[QuadCache]:
        """Active quadtree cache, or None when caching is disabled."""
        return self._quad_cache

    @property
    def paint_cache(self) -> PaintSpecializationCache:
        """Polymorphic specialization cache for typed paint IRs."""
        return self._paint_cache

    def render(self, root: Scene) -> Surface:
        if self._quad_cache is not None:
            return self._quad_cache.render(root)
        layers = as_z_list(root)
        surface = ArraySurface(self.width, self.height)
        if try_paint_layers(
            self.width,
            self.height,
            0,
            0,
            self.width,
            self.height,
            layers,
            surface,
            self._paint_cache,
        ):
            return surface
        for y in range(self.height):
            local_y = y + 0.5 - self.height / 2.0
            for x in range(self.width):
                local_x = x + 0.5 - self.width / 2.0
                surface.set_pixel(x, y, accumulate_pixel(layers, local_x, local_y))
        return surface

    def pick(self, root: Scene, vx: float, vy: float) -> Optional[PickResult]:
        layers = as_z_list(root)
        local_x, local_y = self.viewport_to_root_local(vx, vy)
        for obj in reversed(layers):
            if (picked := obj.pick_target(local_x, local_y)):
                target, x, y = picked
                return PickResult(target=target, local_x=x, local_y=y)
        return None


def accumulate_pixel(layers: Sequence[Shape], x: float, y: float) -> RGBA:
    """Walk closest-to-furthest; src-over each hit; stop when opaque."""
    accum: RGBA = TRANSPARENT
    for obj in reversed(layers):
        if not (layer := obj.color_at(x, y)):
            continue
        accum = src_over(layer, accum)
        if accum[3] >= 255:
            break
    return accum
