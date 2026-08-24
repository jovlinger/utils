"""Hit and color probing for naive per-pixel compositing."""

from __future__ import annotations

from typing import Optional

from imgcomp.object import Object
from imgcomp.rgba import RGBA, modulate
from imgcomp.wrappers import Color, ColorMod, Rotate, Stretch, Translate


def hit_at(obj: Object, x: float, y: float) -> bool:
    """Return True when local coordinate (x, y) hits the object."""
    if isinstance(obj, Translate):
        return hit_at(obj.child, x - obj.tx, y - obj.ty)
    if isinstance(obj, Rotate):
        cx, cy = obj._to_child(x, y)
        return hit_at(obj.child, cx, cy)
    if isinstance(obj, Stretch):
        return hit_at(obj.child, x / obj.scale_x, y / obj.scale_y)
    if isinstance(obj, Color):
        return hit_at(obj.child, x, y)
    if isinstance(obj, ColorMod):
        return hit_at(obj.child, x, y)
    return obj.hit(x, y)


def hit_color(obj: Object, x: float, y: float) -> Optional[RGBA]:
    """Combine hit and color: return straight RGBA when hit, else None."""
    if isinstance(obj, Translate):
        return hit_color(obj.child, x - obj.tx, y - obj.ty)
    if isinstance(obj, Rotate):
        cx, cy = obj._to_child(x, y)
        return hit_color(obj.child, cx, cy)
    if isinstance(obj, Stretch):
        return hit_color(obj.child, x / obj.scale_x, y / obj.scale_y)
    if isinstance(obj, Color):
        if not hit_at(obj.child, x, y):
            return None
        return obj.color
    if isinstance(obj, ColorMod):
        base = hit_color(obj.child, x, y)
        if base is None:
            return None
        return modulate(base, obj.r_mul, obj.g_mul, obj.b_mul, obj.a_mul)
    if not obj.hit(x, y):
        return None
    color = obj.sample(x, y)
    if color[3] <= 0:
        return None
    return color


def pick_target(obj: Object, x: float, y: float) -> Optional[tuple[Object, float, float]]:
    """Return the leaf object and its local coords when (x, y) hits."""
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
