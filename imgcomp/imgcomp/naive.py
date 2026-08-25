"""Pure-Python per-pixel compositor."""

from __future__ import annotations

from typing import Optional

from imgcomp.compositor import Compositor, PickResult
from imgcomp.probe import color_at, pick_target
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.surface import ArraySurface, Surface


class NaiveCompositor(Compositor):
    """For each viewport pixel, walk the z-list and accumulate hit colors."""

    def render(self, root: Scene) -> Surface:
        layers = as_z_list(root)
        surface = ArraySurface(self.width, self.height)
        for y in range(self.height):
            for x in range(self.width):
                local_x = x + 0.5 - self.width / 2.0
                local_y = y + 0.5 - self.height / 2.0
                surface.set_pixel(x, y, self._accumulate_pixel(layers, local_x, local_y))
        return surface

    def pick(self, root: Scene, vx: float, vy: float) -> Optional[PickResult]:
        layers = as_z_list(root)
        local_x, local_y = self.viewport_to_root_local(vx, vy)
        for obj in reversed(layers):
            picked = pick_target(obj, local_x, local_y)
            if picked is not None:
                target, x, y = picked
                return PickResult(target=target, local_x=x, local_y=y)
        return None

    def _accumulate_pixel(self, layers: tuple[object, ...], x: float, y: float) -> RGBA:
        """Walk closest-to-furthest; src-over each hit; stop when opaque."""
        accum: RGBA = TRANSPARENT
        for obj in reversed(layers):
            layer = color_at(obj, x, y)
            if layer is None:
                continue
            accum = src_over(layer, accum)
            if accum[3] >= 255:
                break
        return accum
