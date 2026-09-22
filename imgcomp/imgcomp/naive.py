"""Pure-Python per-pixel compositor."""

from __future__ import annotations

from typing import Optional, Sequence

from imgcomp.compositor import Compositor, PickResult
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import Shape
from imgcomp.surface import ArraySurface, Surface


class NaiveCompositor(Compositor):
    """For each viewport pixel, walk the z-list and accumulate hit colors."""

    def render(self, root: Scene) -> Surface:
        layers = as_z_list(root)
        surface = ArraySurface(self.width, self.height)
        for y in range(self.height):
            gy = y + 0.5 - self.height / 2.0
            for x in range(self.width):
                gx = x + 0.5 - self.width / 2.0
                surface.set_pixel(x, y, accumulate_pixel(layers, gx, gy))
        return surface

    def pick(self, root: Scene, vx: float, vy: float) -> Optional[PickResult]:
        layers = as_z_list(root)
        gx, gy = self.viewport_to_root_local(vx, vy)
        for obj in reversed(layers):
            if (picked := obj.pick_target(gx, gy)):
                target, x, y = picked
                return PickResult(target=target, local_x=x, local_y=y)
        return None


def accumulate_pixel(layers: Sequence[Shape], gx: float, gy: float) -> RGBA:
    """Walk closest-to-furthest; src-over each hit; stop when opaque."""
    accum: RGBA = TRANSPARENT
    for obj in reversed(layers):
        if not (layer := obj.color_at(gx, gy)):
            continue
        accum = src_over(layer, accum)
        if accum[3] >= 255:
            break
    return accum
