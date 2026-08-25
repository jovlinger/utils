"""Color probing for naive per-pixel compositing."""

from __future__ import annotations

from typing import Optional

from imgcomp.compound import Union
from imgcomp.rgba import RGBA, TRANSPARENT, modulate, src_over
from imgcomp.shape import Shape
from imgcomp.wrappers import Color, ColorMod, Rotate, Stretch, Translate


def color_at(obj: Shape, x: float, y: float) -> Optional[RGBA]:
    """Return straight RGBA when (x, y) hits, else None."""
    if isinstance(obj, Union):
        accum: RGBA = TRANSPARENT
        for member in reversed(obj.members):
            layer = color_at(member, x, y)
            if layer is None:
                continue
            accum = src_over(layer, accum)
            if accum[3] >= 255:
                break
        return accum if accum[3] > 0 else None
    if isinstance(obj, Translate):
        return color_at(obj.child, x - obj.tx, y - obj.ty)
    if isinstance(obj, Rotate):
        cx, cy = obj._to_child(x, y)
        return color_at(obj.child, cx, cy)
    if isinstance(obj, Stretch):
        return color_at(obj.child, x / obj.scale_x, y / obj.scale_y)
    if isinstance(obj, Color):
        if color_at(obj.child, x, y) is None:
            return None
        return obj.color
    if isinstance(obj, ColorMod):
        base = color_at(obj.child, x, y)
        if base is None:
            return None
        return modulate(base, obj.r_mul, obj.g_mul, obj.b_mul, obj.a_mul)
    if not obj.hit(x, y):
        return None
    color = obj.sample(x, y)
    if color[3] <= 0:
        return None
    return color


def pick_target(obj: Shape, x: float, y: float) -> Optional[tuple[Shape, float, float]]:
    """Return the leaf shape and its local coords when (x, y) hits."""
    if isinstance(obj, Union):
        for member in reversed(obj.members):
            picked = pick_target(member, x, y)
            if picked is not None:
                return picked
        return None
    if isinstance(obj, Translate):
        return pick_target(obj.child, x - obj.tx, y - obj.ty)
    if isinstance(obj, Rotate):
        cx, cy = obj._to_child(x, y)
        return pick_target(obj.child, cx, cy)
    if isinstance(obj, Stretch):
        return pick_target(obj.child, x / obj.scale_x, y / obj.scale_y)
    if isinstance(obj, Color):
        return pick_target(obj.child, x, y)
    if isinstance(obj, ColorMod):
        return pick_target(obj.child, x, y)
    if obj.hit(x, y):
        return obj, x, y
    return None
