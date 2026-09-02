"""Pure-Python quadtree leaf-cell compositor (reference color_at path)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional, Sequence

from imgcomp.compositor import Compositor, PickResult
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import AABB, Shape
from imgcomp.surface import ArraySurface, Surface

if TYPE_CHECKING:
    from imgcomp.render_profile import RenderProfile


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


def _paint_leaf_cell_python(
    surface: Surface,
    bounds: AABB,
    members: Sequence[Shape],
    width: int,
    height: int,
) -> None:
    """Paint every pixel center inside a quadtree leaf AABB."""
    if not members:
        return
    half_w = width / 2.0
    half_h = height / 2.0
    px_start = max(0, int(math.ceil(bounds.xmin + half_w - 0.5)))
    px_end = min(width - 1, int(math.floor(bounds.xmax + half_w - 0.5)))
    if px_start > px_end:
        return
    py_start = max(0, int(math.ceil(bounds.ymin + half_h - 0.5)))
    py_end = min(height - 1, int(math.floor(bounds.ymax + half_h - 0.5)))
    if py_start > py_end:
        return
    for py in range(py_start, py_end + 1):
        gy = py + 0.5 - half_h
        for px in range(px_start, px_end + 1):
            gx = px + 0.5 - half_w
            surface.set_pixel(px, py, accumulate_pixel(members, gx, gy))


def render_quadtree_python(
    scene: Scene,
    width: int,
    height: int,
    *,
    max_depth: int = 8,
    min_size: float = 16.0,
    profile: RenderProfile | None = None,
) -> Surface:
    """Render via quadtree leaf-cell batch (pure Python color_at)."""
    from imgcomp.render_profile import phase
    from imgcomp.stacklang_render import (
        _iter_leaf_nodes,
        build_quadtree,
        prepare_shape_layers,
        viewport_aabb,
    )

    with phase(profile, "prepare_shape_layers"):
        render_layers = prepare_shape_layers(scene)
    with phase(profile, "build_quadtree"):
        tree = build_quadtree(
            render_layers,
            viewport_aabb(width, height),
            max_depth=max_depth,
            min_size=min_size,
        )
    surface = ArraySurface(width, height, fill=TRANSPARENT)
    with phase(profile, "pixel_driver"):
        for leaf in _iter_leaf_nodes(tree):
            if leaf.zlist is None:
                continue
            _paint_leaf_cell_python(
                surface, leaf.bounds, leaf.zlist.members, width, height
            )
    return surface


class NaiveCompositor(Compositor):
    """Quadtree leaf-cell batch compositor (Python color_at reference)."""

    def render(
        self,
        root: Scene,
        *,
        max_depth: int = 8,
        min_size: float = 16.0,
        profile: RenderProfile | None = None,
    ) -> Surface:
        return render_quadtree_python(
            root,
            self.width,
            self.height,
            max_depth=max_depth,
            min_size=min_size,
            profile=profile,
        )

    def pick(self, root: Scene, vx: float, vy: float) -> Optional[PickResult]:
        layers = as_z_list(root)
        gx, gy = self.viewport_to_root_local(vx, vy)
        for obj in reversed(layers):
            if (picked := obj.pick_target(gx, gy)):
                target, x, y = picked
                return PickResult(target=target, local_x=x, local_y=y)
        return None
