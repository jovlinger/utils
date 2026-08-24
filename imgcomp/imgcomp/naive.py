"""Pure-Python depth-first compositor."""

from __future__ import annotations

from typing import Optional

from imgcomp.compositor import Compositor, PickResult
from imgcomp.object import Object
from imgcomp.rgba import RGBA, TRANSPARENT, modulate, src_over
from imgcomp.surface import ArraySurface, Surface
from imgcomp.wrappers import ColorMod, Group, Rotate, Translate


class NaiveCompositor(Compositor):
    """Pull-sample each viewport pixel depth-first with src-over blending."""

    def render(self, root: Object) -> Surface:
        surface = ArraySurface(self.width, self.height)
        for y in range(self.height):
            for x in range(self.width):
                local_x = x + 0.5 - self.width / 2.0
                local_y = y + 0.5 - self.height / 2.0
                color = self._sample(root, local_x, local_y)
                surface.set_pixel(x, y, color)
        return surface

    def pick(self, root: Object, vx: float, vy: float) -> Optional[PickResult]:
        local_x, local_y = self.viewport_to_root_local(vx, vy)
        return self._pick(root, local_x, local_y)

    def _sample(self, obj: Object, x: float, y: float) -> RGBA:
        if isinstance(obj, Group):
            color = TRANSPARENT
            for child in obj.children:
                color = src_over(color, self._sample(child, x, y))
            return color
        if isinstance(obj, Translate):
            return self._sample(obj.child, x - obj.tx, y - obj.ty)
        if isinstance(obj, Rotate):
            cx, cy = obj._to_child(x, y)
            return self._sample(obj.child, cx, cy)
        if isinstance(obj, ColorMod):
            sampled = self._sample(obj.child, x, y)
            return modulate(sampled, obj.r_mul, obj.g_mul, obj.b_mul, obj.a_mul)
        return obj.sample(x, y)

    def _pick(self, obj: Object, x: float, y: float) -> Optional[PickResult]:
        if isinstance(obj, Group):
            for child in reversed(obj.children):
                picked = self._pick(child, x, y)
                if picked is not None:
                    return picked
            return None
        if isinstance(obj, Translate):
            return self._pick(obj.child, x - obj.tx, y - obj.ty)
        if isinstance(obj, Rotate):
            cx, cy = obj._to_child(x, y)
            return self._pick(obj.child, cx, cy)
        if isinstance(obj, ColorMod):
            return self._pick(obj.child, x, y)
        if obj.hit(x, y):
            return PickResult(target=obj, local_x=x, local_y=y)
        return None
