"""Structural cache keys and conservative AABBs for scene shapes."""

from __future__ import annotations

from typing import Hashable, Optional, Sequence, Tuple

from imgcomp.shape import AABB, Shape

# Local-space axis-aligned box: (xmin, ymin, xmax, ymax).
Aabb = Tuple[float, float, float, float]


def content_key(obj: Shape) -> Tuple[Hashable, ...]:
    """Structural key for cache identity (parameters that affect pixels)."""
    return obj.cachekey()


def approx_aabb(obj: Shape) -> Optional[Aabb]:
    """Conservative local AABB tuple, or None when extent is infinite / unknown."""
    bounds = obj.AABB()
    if bounds is None:
        return None
    return bounds.as_tuple()


def aabbs_intersect(left: Aabb, right: Aabb) -> bool:
    return AABB(*left).intersects(AABB(*right))


def shapes_for_tile(
    layers: Sequence[Shape], tile_aabb: Aabb
) -> tuple[Shape, ...]:
    """Return layers that may cover tile_aabb (conservative)."""
    query = AABB(*tile_aabb)
    selected: list[Shape] = []
    for layer in layers:
        if layer.maybe_intersect_rect(query):
            selected.append(layer)
    return tuple(selected)


def region_content_key(layers: Sequence[Shape], tile_aabb: Aabb) -> Tuple[Hashable, ...]:
    """Hash of the z-list slice that may affect a tile."""
    return tuple(content_key(layer) for layer in shapes_for_tile(layers, tile_aabb))
