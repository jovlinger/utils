"""Structural cache keys and conservative AABBs for scene shapes."""

from __future__ import annotations

import math
from typing import Hashable, Iterable, Optional, Sequence, Tuple

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
from imgcomp.shape import Shape
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
    """Conservative local AABB, or None when extent is infinite / unknown."""
    if isinstance(obj, Infinite):
        return None
    if isinstance(obj, Circle):
        radius = obj.radius
        return (-radius, -radius, radius, radius)
    if isinstance(obj, Rectangle):
        return (-obj.half_width, -obj.half_height, obj.half_width, obj.half_height)
    if isinstance(obj, Oval):
        return (-obj.radius_x, -obj.radius_y, obj.radius_x, obj.radius_y)
    if isinstance(obj, ImageObject):
        half_w = obj.width / 2.0
        half_h = obj.height / 2.0
        return (-half_w, -half_h, half_w, half_h)
    if isinstance(obj, Translate):
        child = approx_aabb(obj.child)
        if child is None:
            return None
        return (
            child[0] + obj.tx,
            child[1] + obj.ty,
            child[2] + obj.tx,
            child[3] + obj.ty,
        )
    if isinstance(obj, Rotate):
        child = approx_aabb(obj.child)
        if child is None:
            return None
        return _rotate_aabb(child, obj.degrees)
    if isinstance(obj, Stretch):
        child = approx_aabb(obj.child)
        if child is None:
            return None
        return _stretch_aabb(child, obj.scale_x, obj.scale_y)
    if isinstance(obj, (Color, ColorMod)):
        return approx_aabb(obj.child)
    if isinstance(obj, Union):
        return _union_aabbs(approx_aabb(member) for member in obj.members)
    if isinstance(obj, (Subtract, Intersect)):
        return _union_aabbs((approx_aabb(obj.left), approx_aabb(obj.right)))
    if isinstance(obj, Fatten):
        child = approx_aabb(obj.inner)
        if child is None:
            return None
        pad = abs(obj.amount)
        return (child[0] - pad, child[1] - pad, child[2] + pad, child[3] + pad)
    if isinstance(obj, Thin):
        return approx_aabb(obj.inner)
    if isinstance(obj, RotateShape):
        child = approx_aabb(obj.inner)
        if child is None:
            return None
        return _rotate_aabb(child, obj.degrees)
    if isinstance(obj, StretchShape):
        child = approx_aabb(obj.inner)
        if child is None:
            return None
        return _stretch_aabb(child, obj.scale_x, obj.scale_y)
    if isinstance(obj, SDFShape):
        return None
    return None


def aabbs_intersect(left: Aabb, right: Aabb) -> bool:
    return not (
        left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1]
    )


def shapes_for_tile(
    layers: Sequence[Shape], tile_aabb: Aabb
) -> tuple[Shape, ...]:
    """Return layers that may cover tile_aabb (conservative)."""
    selected: list[Shape] = []
    for layer in layers:
        bounds = approx_aabb(layer)
        if bounds is None or aabbs_intersect(bounds, tile_aabb):
            selected.append(layer)
    return tuple(selected)


def region_content_key(layers: Sequence[Shape], tile_aabb: Aabb) -> Tuple[Hashable, ...]:
    """Hash of the z-list slice that may affect a tile."""
    return tuple(content_key(layer) for layer in shapes_for_tile(layers, tile_aabb))


def _rotate_aabb(box: Aabb, degrees: float) -> Aabb:
    cos_a = math.cos(math.radians(degrees))
    sin_a = math.sin(math.radians(degrees))
    corners = (
        (box[0], box[1]),
        (box[0], box[3]),
        (box[2], box[1]),
        (box[2], box[3]),
    )
    xs: list[float] = []
    ys: list[float] = []
    for x, y in corners:
        # Inverse of Rotate wrapper: parent <- child uses +y down convention.
        xs.append(x * cos_a - y * sin_a)
        ys.append(x * sin_a + y * cos_a)
    return (min(xs), min(ys), max(xs), max(ys))


def _stretch_aabb(box: Aabb, scale_x: float, scale_y: float) -> Aabb:
    xs = (box[0] * scale_x, box[2] * scale_x)
    ys = (box[1] * scale_y, box[3] * scale_y)
    return (min(xs), min(ys), max(xs), max(ys))


def _union_aabbs(boxes: Iterable[Optional[Aabb]]) -> Optional[Aabb]:
    xmin = ymin = math.inf
    xmax = ymax = -math.inf
    saw_box = False
    for box in boxes:
        if box is None:
            return None
        saw_box = True
        xmin = min(xmin, box[0])
        ymin = min(ymin, box[1])
        xmax = max(xmax, box[2])
        ymax = max(ymax, box[3])
    if not saw_box:
        return None
    return (xmin, ymin, xmax, ymax)
