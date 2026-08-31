"""Stacklang render: surf shape graph, quadtree z-lists, stacklang pixel walk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from imgcomp import _stack_c as _cy
from imgcomp import _stacklang_render_c as _slr
from imgcomp import stack_c as sc
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import AABB, Bounds, Shape, StackLangBody
from imgcomp.surface import ArraySurface, Surface
from imgcomp.shapes import set_using_stacklang
from imgcomp.stacklang_debug import log_py_to_c


@dataclass(frozen=True)
class SceneLayer:
    """One scene z-layer root and its color_at stacklang program."""

    index: int
    shape: Shape
    color_stacklang: StackLangBody

    @property
    def global_bounds(self) -> Bounds | None:
        return self.shape.bounds()

    @property
    def global_aabb(self) -> AABB | None:
        bounds = self.global_bounds
        if bounds is None:
            return None
        return bounds.to_aabb()


@dataclass(frozen=True)
class QuadNode:
    """Quadtree node: either a leaf bucket of layers or four children."""

    bounds: AABB
    layers: tuple[SceneLayer, ...] | None = None
    children: tuple[QuadNode, QuadNode, QuadNode, QuadNode] | None = None


def prepare_scene(scene: Scene) -> list[SceneLayer]:
    """Surf scene z-list; each layer asks its root shape for surface lang."""
    layers: list[SceneLayer] = []
    for layer_index, layer_shape in enumerate(as_z_list(scene)):
        layers.append(
            SceneLayer(
                index=layer_index,
                shape=layer_shape,
                color_stacklang=layer_shape.color_at_stacklang(),
            )
        )
    return layers


def viewport_aabb(width: int, height: int) -> AABB:
    half_w = width / 2.0
    half_h = height / 2.0
    return AABB(-half_w, -half_h, half_w - 1.0, half_h - 1.0)


def _intersecting_layers(
    layers: Sequence[SceneLayer], bounds: AABB
) -> tuple[SceneLayer, ...]:
    selected: list[SceneLayer] = []
    for layer in layers:
        box = layer.global_bounds
        if box is None or box.intersects_aabb(bounds):
            selected.append(layer)
    return tuple(selected)


## FIXME. this takes whole compound objects, and we ask AABB intersect here.  Instead we should give the Shaoe the AABB and
## ask it to build the subset of itself that could overlap.   This means that unions will return versions of themselves with
## smaller member sets.  Similarly other componds
def build_quadtree(
    layers: Sequence[SceneLayer],
    bounds: AABB,
    *,
    max_depth: int = 8,
    max_per_leaf: int = 4,
    min_size: float = 4.0,
) -> QuadNode:
    """Build a quadtree over scene layer roots (back-to-front z-order preserved)."""
    here = _intersecting_layers(layers, bounds)
    width = bounds.xmax - bounds.xmin
    height = bounds.ymax - bounds.ymin
    if (
        max_depth <= 0
        or len(here) <= max_per_leaf
        or width <= min_size
        or height <= min_size
    ):
        return QuadNode(bounds=bounds, layers=here)

    mid_x = (bounds.xmin + bounds.xmax) / 2.0
    mid_y = (bounds.ymin + bounds.ymax) / 2.0
    nw = AABB(bounds.xmin, bounds.ymin, mid_x, mid_y)
    ne = AABB(mid_x, bounds.ymin, bounds.xmax, mid_y)
    sw = AABB(bounds.xmin, mid_y, mid_x, bounds.ymax)
    se = AABB(mid_x, mid_y, bounds.xmax, bounds.ymax)
    child_depth = max_depth - 1
    return QuadNode(
        bounds=bounds,
        children=(
            build_quadtree(here, nw, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size),
            build_quadtree(here, ne, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size),
            build_quadtree(here, sw, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size),
            build_quadtree(here, se, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size),
        ),
    )


def z_list_at_point(node: QuadNode, gx: float, gy: float) -> tuple[SceneLayer, ...]:
    """Return culled scene layers at a global point."""
    if node.layers is not None:
        return node.layers
    assert node.children is not None
    for child in node.children:
        if (
            child.bounds.xmin <= gx <= child.bounds.xmax
            and child.bounds.ymin <= gy <= child.bounds.ymax
        ):
            return z_list_at_point(child, gx, gy)
    return ()


def color_at_layer(layer: SceneLayer, gx: float, gy: float) -> RGBA | None:
    """Reference color_at for a full layer root in scene space."""
    return layer.shape.color_at(gx, gy)


def accumulate_layers(
    layers: Sequence[SceneLayer],
    z_list: Sequence[SceneLayer],
    gx: float,
    gy: float,
) -> RGBA:
    """Composite scene layers back-to-front (reference path)."""
    present = {layer.index for layer in z_list}
    accum: RGBA = TRANSPARENT
    for layer_index in range(len(layers) - 1, -1, -1):
        if layer_index not in present:
            continue
        if not (hit := color_at_layer(layers[layer_index], gx, gy)):
            continue
        accum = src_over(hit, accum)
        if accum[3] >= 255:
            break
    return accum


def _vm_body(
    stacklang: StackLangBody,
    *,
    owner: Shape,
    shape_objects: list[Shape],
    dup_xy: Any,
    dup_anchor_push_xy: Any,
    float_max2: Any,
    offset_xy_sub: Any,
    rgba_solid_if_hit: Any,
    circle_distance: Any,
    rectangle_distance: Any,
    oval_distance: Any,
    fill_white: Any,
    rgba_transparent: Any,
    src_over_layer: Any,
    sdf_fill_white: Any,
    python_color_at: Any,
    python_distance: Any,
) -> list[Any]:
    """Map shape stacklang into a ``stack_c.register_op`` authoring list."""
    body: list[Any] = []
    pending_shape_index: int | None = None
    index = 0
    while index < len(stacklang):
        token = stacklang[index]
        if isinstance(token, Shape):
            pending_shape_index = len(shape_objects)
            shape_objects.append(token)
            index += 1
            continue
        if token == "dup_xy":
            body.append(dup_xy)
            index += 1
            continue
        if token == "dup_anchor_push_xy":
            body.append(dup_anchor_push_xy)
            index += 1
            continue
        if token == "float_max2":
            body.append(float_max2)
            index += 1
            continue
        if token == "offset_xy_sub":
            body.append(offset_xy_sub)
            index += 1
            continue
        if token == "rgba_solid_if_hit":
            body.append(rgba_solid_if_hit)
            index += 1
            continue
        if token == "circle_distance":
            body.append(circle_distance)
            index += 1
            continue
        if token == "rectangle_distance":
            body.append(rectangle_distance)
            index += 1
            continue
        if token == "oval_distance":
            body.append(oval_distance)
            index += 1
            continue
        if token == "fill_white":
            body.append(fill_white)
            index += 1
            continue
        if token == "rgba_transparent":
            body.append(rgba_transparent)
            index += 1
            continue
        if token == "src_over_layer":
            body.append(src_over_layer)
            index += 1
            continue
        if token == "sdf_fill_white":
            body.append(sdf_fill_white)
            index += 1
            continue
        if token == "call_python_method":
            if index + 1 >= len(stacklang):
                raise ValueError("call_python_method requires a method name")
            method = stacklang[index + 1]
            index += 2
            if method in ("color_at", "distance"):
                shape_index = pending_shape_index
                if shape_index is None:
                    shape_index = len(shape_objects)
                    shape_objects.append(owner)
                if method == "color_at":
                    body.extend([float(shape_index), python_color_at])
                else:
                    body.extend([float(shape_index), python_distance])
                pending_shape_index = None
                continue
            raise NotImplementedError(f"call_python_method: {method!r}")
        if isinstance(token, (int, float)):
            body.append(float(token))
            index += 1
            continue
        if isinstance(token, str):
            raise NotImplementedError(f"stacklang token: {token!r}")
        raise TypeError(f"stacklang token: {token!r}")
    return body


def _register_render_vm(
    width: int,
    height: int,
    layers: Sequence[SceneLayer],
) -> tuple[list[int], list[Shape]]:
    """Register float_incr_le pixel loops and per-layer surface-lang bodies."""
    sc.reset_vm()
    sc.register_base_ops()
    set_gy = sc.register_op("slr_set_gy", _slr.slr_set_gy)
    dup_xy = sc.register_op("slr_dup_xy", _slr.slr_dup_xy)
    dup_anchor_push_xy = sc.register_op("slr_dup_anchor_push_xy", _slr.slr_dup_anchor_push_xy)
    float_max2 = sc.register_op("slr_float_max2", _slr.slr_float_max2)
    offset_xy_sub = sc.register_op("slr_offset_xy_sub", _slr.slr_offset_xy_sub)
    rgba_solid_if_hit = sc.register_op("slr_rgba_solid_if_hit", _slr.slr_rgba_solid_if_hit)
    circle_distance = sc.register_op("slr_circle_distance", _slr.slr_circle_distance)
    rectangle_distance = sc.register_op("slr_rectangle_distance", _slr.slr_rectangle_distance)
    oval_distance = sc.register_op("slr_oval_distance", _slr.slr_oval_distance)
    fill_white = sc.register_op("slr_fill_white", _slr.slr_fill_white)
    rgba_transparent = sc.register_op("slr_rgba_transparent", _slr.slr_rgba_transparent)
    src_over_layer = sc.register_op("slr_src_over_layer", _slr.slr_src_over_layer)
    sdf_fill_white = sc.register_op("slr_sdf_fill_white", _slr.slr_sdf_fill_white)
    python_color_at = sc.register_op("slr_python_color_at", _slr.slr_python_color_at)
    python_distance = sc.register_op("slr_python_distance", _slr.slr_python_distance)
    paint = sc.register_op("slr_paint_pixel", _slr.slr_paint_pixel)

    layer_op_ids: list[int] = []
    shape_objects: list[Shape] = []
    for layer_index, layer in enumerate(layers):
        body = _vm_body(
            layer.color_stacklang,
            owner=layer.shape,
            shape_objects=shape_objects,
            dup_xy=dup_xy,
            dup_anchor_push_xy=dup_anchor_push_xy,
            float_max2=float_max2,
            offset_xy_sub=offset_xy_sub,
            rgba_solid_if_hit=rgba_solid_if_hit,
            circle_distance=circle_distance,
            rectangle_distance=rectangle_distance,
            oval_distance=oval_distance,
            fill_white=fill_white,
            rgba_transparent=rgba_transparent,
            src_over_layer=src_over_layer,
            sdf_fill_white=sdf_fill_white,
            python_color_at=python_color_at,
            python_distance=python_distance,
        )
        layer_op_ids.append(sc.register_op(f"layer_{layer_index}", body).op_id)

    half_w = width / 2.0
    half_h = height / 2.0
    gx0 = 0.5 - half_w
    gx1 = (width - 1) + 0.5 - half_w
    gy0 = 0.5 - half_h
    gy1 = (height - 1) + 0.5 - half_h
    col_loop = sc.register_op(
        "render_col",
        [set_gy, gx0, gx1, 1.0, sc.lit_op, paint, sc.float_incr_le],
    )
    sc.register_op(
        "render",
        [gy0, gy1, 1.0, sc.lit_op, col_loop, sc.float_incr_le],
    )
    return layer_op_ids, shape_objects


def render(
    scene: Scene,
    width: int,
    height: int,
    *,
    max_depth: int = 8,
) -> Surface:
    """Stacklang render: surf graph, quadtree z-lists, float_incr_le pixel walk."""
    render_layers = prepare_scene(scene)
    tree = build_quadtree(render_layers, viewport_aabb(width, height), max_depth=max_depth)
    surface = ArraySurface(width, height, fill=TRANSPARENT)
    layer_op_ids, shape_objects = _register_render_vm(width, height, render_layers)
    _slr.bind_render(
        surface.pixel_buffer(),
        width,
        height,
        tree,
        list(render_layers),
        layer_op_ids,
        shape_objects,
        len(render_layers),
    )
    log_py_to_c("run_op", op="render", width=width, height=height, layers=len(render_layers))
    set_using_stacklang(True)
    try:
        _cy.run_op("render")
    finally:
        set_using_stacklang(False)
    log_py_to_c("run_op_return", op="render", width=width, height=height)
    return surface
