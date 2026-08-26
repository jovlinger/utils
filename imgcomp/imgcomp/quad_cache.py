"""Quadtree tile cache keyed by structural z-list slices."""

from __future__ import annotations

from array import array
from typing import Dict, Hashable, Optional, Sequence, Tuple

from imgcomp.content_key import Aabb, region_content_key, shapes_for_tile
from imgcomp.paint_cache import PaintSpecializationCache, try_paint_layers_to_buffer
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import Shape
from imgcomp.surface import ArraySurface, Surface

TileKey = Tuple[Hashable, ...]


class QuadCache:
    """Memoize leaf tiles by (rect, content-key of shapes covering that rect).

    Intended for animation: static regions keep their keys across frames while
    only tiles whose contributing z-list changes are re-rasterized.
    """

    def __init__(
        self,
        width: int,
        height: int,
        *,
        min_tile: int = 16,
        paint_cache: Optional[PaintSpecializationCache] = None,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        if min_tile <= 0:
            raise ValueError("min_tile must be positive")
        self.width = width
        self.height = height
        self.min_tile = min_tile
        self._tiles: Dict[TileKey, array[int]] = {}
        self._paint_cache = paint_cache if paint_cache is not None else PaintSpecializationCache()
        self.hits: int = 0
        self.misses: int = 0

    def clear(self) -> None:
        self._tiles.clear()
        self.hits = 0
        self.misses = 0

    def resize(self, width: int, height: int) -> None:
        if width == self.width and height == self.height:
            return
        self.width = width
        self.height = height
        self.clear()

    def stats(self) -> Dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self._tiles),
        }

    def render(self, root: Scene) -> Surface:
        layers = as_z_list(root)
        out = ArraySurface(self.width, self.height)
        self._fill_quad(0, 0, self.width, self.height, layers, out)
        return out

    def _fill_quad(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        layers: Sequence[Shape],
        out: ArraySurface,
    ) -> None:
        tile_w = x1 - x0
        tile_h = y1 - y0
        tile_aabb = self._tile_aabb(x0, y0, x1, y1)
        key: TileKey = (x0, y0, x1, y1, region_content_key(layers, tile_aabb))
        cached = self._tiles.get(key)
        if cached is not None:
            self.hits += 1
            self._blit(cached, x0, y0, tile_w, tile_h, out)
            return

        if tile_w <= self.min_tile or tile_h <= self.min_tile or tile_w == 1 or tile_h == 1:
            pixels = self._rasterize(x0, y0, x1, y1, layers, tile_aabb)
            self._tiles[key] = pixels
            self.misses += 1
            self._blit(pixels, x0, y0, tile_w, tile_h, out)
            return

        mx = x0 + tile_w // 2
        my = y0 + tile_h // 2
        self._fill_quad(x0, y0, mx, my, layers, out)
        self._fill_quad(mx, y0, x1, my, layers, out)
        self._fill_quad(x0, my, mx, y1, layers, out)
        self._fill_quad(mx, my, x1, y1, layers, out)

    def _tile_aabb(self, x0: int, y0: int, x1: int, y1: int) -> Aabb:
        half_w = self.width / 2.0
        half_h = self.height / 2.0
        return (x0 - half_w, y0 - half_h, x1 - half_w, y1 - half_h)

    def _rasterize(
        self,
        x0: int,
        y0: int,
        x1: int,
        y1: int,
        layers: Sequence[Shape],
        tile_aabb: Aabb,
    ) -> array[int]:
        from imgcomp.naive import accumulate_pixel

        contributors = shapes_for_tile(layers, tile_aabb)
        tile_w = x1 - x0
        tile_h = y1 - y0
        pixels: array[int] = array("B", [0]) * (tile_w * tile_h * 4)
        if try_paint_layers_to_buffer(
            self.width,
            self.height,
            x0,
            y0,
            x1,
            y1,
            contributors,
            pixels,
            self._paint_cache,
        ):
            return pixels

        half_w = self.width / 2.0
        half_h = self.height / 2.0
        index = 0
        for y in range(y0, y1):
            local_y = y + 0.5 - half_h
            for x in range(x0, x1):
                local_x = x + 0.5 - half_w
                color = accumulate_pixel(contributors, local_x, local_y)
                pixels[index] = color[0]
                pixels[index + 1] = color[1]
                pixels[index + 2] = color[2]
                pixels[index + 3] = color[3]
                index += 4
        return pixels

    def _blit(
        self,
        pixels: array[int],
        x0: int,
        y0: int,
        tile_w: int,
        tile_h: int,
        out: ArraySurface,
    ) -> None:
        index = 0
        for row in range(tile_h):
            for col in range(tile_w):
                out.set_pixel(
                    x0 + col,
                    y0 + row,
                    (
                        pixels[index],
                        pixels[index + 1],
                        pixels[index + 2],
                        pixels[index + 3],
                    ),
                )
                index += 4
