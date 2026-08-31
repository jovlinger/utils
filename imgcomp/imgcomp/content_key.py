"""Structural cache keys and conservative AABBs for scene shapes."""

from __future__ import annotations

from typing import Hashable, Optional, Sequence, Tuple

from imgcomp.compound import (
    Fatten,
    Intersect,
    RotateShape,
    StretchShape,
    Subtract,
    Thin,
    Union,
)
from imgcomp.primitives import ImageObject
from imgcomp.shape import AABB, Shape
from imgcomp.shapes import Circle, Infinite, Oval, Rectangle, SDFShape
from imgcomp.wrappers import Color, ColorMod, Rotate, Stretch, Translate

# Local-space axis-aligned box: (xmin, ymin, xmax, ymax).
Aabb = Tuple[float, float, float, float]


def content_key(obj: Shape) -> Tuple[Hashable, ...]:
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
    if isinstance(obj, Union):
        return ("union", tuple(content_key(member) for member in obj.members))
    if isinstance(obj, Subtract):
        return ("subtract", content_key(obj.left), content_key(obj.right))
    if isinstance(obj, Intersect):
        return ("intersect", content_key(obj.left), content_key(obj.right))
    if isinstance(obj, Fatten):
        return ("fatten", obj.amount, content_key(obj.inner))
    if isinstance(obj, Thin):
        return ("thin", obj.amount, content_key(obj.inner))
    if isinstance(obj, RotateShape):
        return ("rotate_shape", obj.degrees, content_key(obj.inner))
    if isinstance(obj, StretchShape):
        return ("stretch_shape", obj.scale_x, obj.scale_y, content_key(obj.inner))
    if isinstance(obj, Circle):
        return ("circle", obj.radius)
    if isinstance(obj, Rectangle):
        return ("rect", obj.half_width, obj.half_height)
    if isinstance(obj, Oval):
        return ("oval", obj.radius_x, obj.radius_y)
    if isinstance(obj, Infinite):
        return ("infinite",)
    if isinstance(obj, ImageObject):
        return ("image", obj.width, obj.height, id(obj))
    if isinstance(obj, SDFShape):
        return ("sdfshape", type(obj).__name__, id(obj))
    return ("object", type(obj).__name__, id(obj))


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
