"""Stacklang render: surf shape graph, quadtree z-lists, stacklang pixel walk."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Hashable, Sequence

from imgcomp import _stack_c as _cy
from imgcomp import _stacklang_render_c as _slr
from imgcomp import stack_c as sc
from imgcomp.intersect_cache import intersect_cache_session
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import AABB, Bounds, Shape, StackLangBody
from imgcomp.surface import ArraySurface, Surface
from imgcomp.shapes import set_using_stacklang
from imgcomp.stack_type import PrePost, flatten_authoring
from imgcomp.stacklang_debug import log_py_to_c


@dataclass(frozen=True)
class SceneLayer:
    """One scene z-layer root and its color_at stacklang program."""

    index: int
    shape: Shape
    color_stacklang: StackLangBody
    paint_op_id: int = -1

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
    return AABB(
        0.5 - half_w,
        0.5 - half_h,
        (width - 1) + 0.5 - half_w,
        (height - 1) + 0.5 - half_h,
    )


def _stacklang_key(stacklang: StackLangBody) -> tuple[Any, ...]:
    return tuple(flatten_authoring(list(stacklang)))


@dataclass
class _CullIntern:
    """Intern culled scene layers and z-lists for identical quadtree cells."""

    _layers: dict[tuple[int, tuple[Hashable, ...]], SceneLayer] = field(
        default_factory=dict
    )
    _zlists: dict[tuple[tuple[int, tuple[Hashable, ...]], ...], tuple[SceneLayer, ...]] = (
        field(default_factory=dict)
    )

    def culled_layer(self, layer: SceneLayer, bounds: AABB) -> SceneLayer | None:
        from imgcomp.intersect_cache import cached_intersected_by

        culled_shape = cached_intersected_by(layer.shape, bounds)
        if culled_shape is None:
            return None
        if culled_shape is layer.shape:
            return layer
        content = culled_shape.cachekey()
        key = (layer.index, content)
        cached = self._layers.get(key)
        if cached is not None:
            return cached
        cached = SceneLayer(
            index=layer.index,
            shape=culled_shape,
            color_stacklang=culled_shape.color_at_stacklang(),
        )
        self._layers[key] = cached
        return cached

    def layers_for_bounds(
        self, layers: Sequence[SceneLayer], bounds: AABB
    ) -> tuple[SceneLayer, ...]:
        selected: list[SceneLayer] = []
        for layer in layers:
            if (culled := self.culled_layer(layer, bounds)) is not None:
                selected.append(culled)
        zlist_key = tuple((layer.index, layer.shape.cachekey()) for layer in selected)
        cached = self._zlists.get(zlist_key)
        if cached is not None:
            return cached
        cached = tuple(selected)
        self._zlists[zlist_key] = cached
        return cached


def _culled_scene_layer(
    layer: SceneLayer, bounds: AABB, intern: _CullIntern
) -> SceneLayer | None:
    """Return a layer view restricted to shapes that may hit ``bounds``."""
    return intern.culled_layer(layer, bounds)


def _layers_for_bounds(
    layers: Sequence[SceneLayer],
    bounds: AABB,
    intern: _CullIntern,
) -> tuple[SceneLayer, ...]:
    return intern.layers_for_bounds(layers, bounds)


def _max_union_members(layers: Sequence[SceneLayer]) -> int:
    """Largest Union arity among layer roots (0 if none)."""
    from imgcomp.compound import Union

    count = 0
    for layer in layers:
        shape = layer.shape
        if isinstance(shape, Union):
            count = max(count, len(shape.members))
    return count


def build_quadtree(
    layers: Sequence[SceneLayer],
    bounds: AABB,
    *,
    max_depth: int = 8,
    max_per_leaf: int = 4,
    min_size: float = 4.0,
    intern: _CullIntern | None = None,
) -> QuadNode:
    """Build a quadtree over scene layer roots (back-to-front z-order preserved)."""
    if intern is None:
        with intersect_cache_session():
            return build_quadtree(
                layers,
                bounds,
                max_depth=max_depth,
                max_per_leaf=max_per_leaf,
                min_size=min_size,
                intern=_CullIntern(),
            )
    here = _layers_for_bounds(layers, bounds, intern)
    width = bounds.xmax - bounds.xmin
    height = bounds.ymax - bounds.ymin
    heavy_union = _max_union_members(here) > max_per_leaf
    if (
        max_depth <= 0
        or (len(here) <= max_per_leaf and not heavy_union)
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
            build_quadtree(here, nw, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
            build_quadtree(here, ne, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
            build_quadtree(here, sw, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
            build_quadtree(here, se, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
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


def _iter_leaf_layers(node: QuadNode) -> list[SceneLayer]:
    if node.layers is not None:
        return list(node.layers)
    assert node.children is not None
    leaves: list[SceneLayer] = []
    for child in node.children:
        leaves.extend(_iter_leaf_layers(child))
    return leaves


def _finalize_paint_op_ids(
    node: QuadNode,
    default_op_ids: Sequence[int],
    culled_op_ids: dict[tuple[Any, ...], int],
) -> QuadNode:
    if node.layers is not None:
        layers = tuple(
            _with_paint_op_id(layer, default_op_ids, culled_op_ids) for layer in node.layers
        )
        return QuadNode(bounds=node.bounds, layers=layers)
    assert node.children is not None
    return QuadNode(
        bounds=node.bounds,
        children=tuple(
            _finalize_paint_op_ids(child, default_op_ids, culled_op_ids)
            for child in node.children
        ),
    )


def _with_paint_op_id(
    layer: SceneLayer,
    default_op_ids: Sequence[int],
    culled_op_ids: dict[tuple[Any, ...], int],
) -> SceneLayer:
    key = _stacklang_key(layer.color_stacklang)
    op_id = culled_op_ids.get(key, default_op_ids[layer.index])
    if layer.paint_op_id == op_id:
        return layer
    return SceneLayer(
        index=layer.index,
        shape=layer.shape,
        color_stacklang=layer.color_stacklang,
        paint_op_id=op_id,
    )


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
    float_neg: Any,
    offset_xy_sub: Any,
    rgba_solid_if_hit: Any,
    circle_distance: Any,
    rectangle_distance: Any,
    oval_distance: Any,
    fill_white: Any,
    rgba_transparent: Any,
    push_transparent_accum: Any,
    dup_anchor_xy: Any,
    drop_hit_xy: Any,
    anchorize_rgba: Any,
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
        if isinstance(token, PrePost):
            body.append(
                PrePost(
                    _vm_body(
                        token.body,
                        owner=owner,
                        shape_objects=shape_objects,
                        dup_xy=dup_xy,
                        dup_anchor_push_xy=dup_anchor_push_xy,
                        float_max2=float_max2,
                        float_neg=float_neg,
                        offset_xy_sub=offset_xy_sub,
                        rgba_solid_if_hit=rgba_solid_if_hit,
                        circle_distance=circle_distance,
                        rectangle_distance=rectangle_distance,
                        oval_distance=oval_distance,
                        fill_white=fill_white,
                        rgba_transparent=rgba_transparent,
                        push_transparent_accum=push_transparent_accum,
                        dup_anchor_xy=dup_anchor_xy,
                        drop_hit_xy=drop_hit_xy,
                        anchorize_rgba=anchorize_rgba,
                        src_over_layer=src_over_layer,
                        sdf_fill_white=sdf_fill_white,
                        python_color_at=python_color_at,
                        python_distance=python_distance,
                    ),
                    pre=token.stack_type.pre,
                    post=token.stack_type.post,
                    label=token.label,
                )
            )
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
        if token == "float_neg":
            body.append(float_neg)
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
        if token == "push_transparent_accum":
            body.append(push_transparent_accum)
            index += 1
            continue
        if token == "dup_anchor_xy":
            body.append(dup_anchor_xy)
            index += 1
            continue
        if token == "drop_hit_xy":
            body.append(drop_hit_xy)
            index += 1
            continue
        if token == "anchorize_rgba":
            body.append(anchorize_rgba)
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
    *,
    extra_layers: Sequence[SceneLayer] = (),
) -> tuple[list[int], list[Shape], dict[tuple[Any, ...], int]]:
    """Register float_incr_le pixel loops and per-layer surface-lang bodies."""
    sc.reset_vm()
    sc.register_base_ops()
    set_gy = sc.register_op("slr_set_gy", _slr.slr_set_gy)
    dup_xy = sc.register_op("slr_dup_xy", _slr.slr_dup_xy)
    dup_anchor_push_xy = sc.register_op("slr_dup_anchor_push_xy", _slr.slr_dup_anchor_push_xy)
    float_max2 = sc.register_op("slr_float_max2", _slr.slr_float_max2)
    float_neg = sc.register_op("slr_float_neg", _slr.slr_float_neg)
    offset_xy_sub = sc.register_op("slr_offset_xy_sub", _slr.slr_offset_xy_sub)
    rgba_solid_if_hit = sc.register_op("slr_rgba_solid_if_hit", _slr.slr_rgba_solid_if_hit)
    circle_distance = sc.register_op("slr_circle_distance", _slr.slr_circle_distance)
    rectangle_distance = sc.register_op("slr_rectangle_distance", _slr.slr_rectangle_distance)
    oval_distance = sc.register_op("slr_oval_distance", _slr.slr_oval_distance)
    fill_white = sc.register_op("slr_fill_white", _slr.slr_fill_white)
    rgba_transparent = sc.register_op("slr_rgba_transparent", _slr.slr_rgba_transparent)
    push_transparent_accum = sc.register_op(
        "slr_push_transparent_accum",
        _slr.slr_push_transparent_accum,
    )
    dup_anchor_xy = sc.register_op("slr_dup_anchor_xy", _slr.slr_dup_anchor_xy)
    drop_hit_xy = sc.register_op("slr_drop_hit_xy", _slr.slr_drop_hit_xy)
    anchorize_rgba = sc.register_op("slr_anchorize_rgba", _slr.slr_anchorize_rgba)
    src_over_layer = sc.register_op("slr_src_over_layer", _slr.slr_src_over_layer)
    sdf_fill_white = sc.register_op("slr_sdf_fill_white", _slr.slr_sdf_fill_white)
    python_color_at = sc.register_op("slr_python_color_at", _slr.slr_python_color_at)
    python_distance = sc.register_op("slr_python_distance", _slr.slr_python_distance)
    paint = sc.register_op("slr_paint_pixel", _slr.slr_paint_pixel)

    layer_op_ids: list[int] = []
    shape_objects: list[Shape] = []
    program_op_ids: dict[tuple[Any, ...], int] = {}
    for layer_index, layer in enumerate(layers):
        key = _stacklang_key(layer.color_stacklang)
        body = _vm_body(
            layer.color_stacklang,
            owner=layer.shape,
            shape_objects=shape_objects,
            dup_xy=dup_xy,
            dup_anchor_push_xy=dup_anchor_push_xy,
            float_max2=float_max2,
            float_neg=float_neg,
            offset_xy_sub=offset_xy_sub,
            rgba_solid_if_hit=rgba_solid_if_hit,
            circle_distance=circle_distance,
            rectangle_distance=rectangle_distance,
            oval_distance=oval_distance,
            fill_white=fill_white,
            rgba_transparent=rgba_transparent,
            push_transparent_accum=push_transparent_accum,
            dup_anchor_xy=dup_anchor_xy,
            drop_hit_xy=drop_hit_xy,
            anchorize_rgba=anchorize_rgba,
            src_over_layer=src_over_layer,
            sdf_fill_white=sdf_fill_white,
            python_color_at=python_color_at,
            python_distance=python_distance,
        )
        op_id = sc.register_op(f"layer_{layer_index}", body).op_id
        layer_op_ids.append(op_id)
        program_op_ids[key] = op_id

    for extra_index, layer in enumerate(extra_layers):
        key = _stacklang_key(layer.color_stacklang)
        if key in program_op_ids:
            continue
        body = _vm_body(
            layer.color_stacklang,
            owner=layer.shape,
            shape_objects=shape_objects,
            dup_xy=dup_xy,
            dup_anchor_push_xy=dup_anchor_push_xy,
            float_max2=float_max2,
            float_neg=float_neg,
            offset_xy_sub=offset_xy_sub,
            rgba_solid_if_hit=rgba_solid_if_hit,
            circle_distance=circle_distance,
            rectangle_distance=rectangle_distance,
            oval_distance=oval_distance,
            fill_white=fill_white,
            rgba_transparent=rgba_transparent,
            push_transparent_accum=push_transparent_accum,
            dup_anchor_xy=dup_anchor_xy,
            drop_hit_xy=drop_hit_xy,
            anchorize_rgba=anchorize_rgba,
            src_over_layer=src_over_layer,
            sdf_fill_white=sdf_fill_white,
            python_color_at=python_color_at,
            python_distance=python_distance,
        )
        program_op_ids[key] = sc.register_op(f"layer_cull_{extra_index}", body).op_id

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
    return layer_op_ids, shape_objects, program_op_ids


def render(
    scene: Scene,
    width: int,
    height: int,
    *,
    max_depth: int = 8,
) -> Surface:
    """Stacklang render: surf graph, quadtree z-lists, float_incr_le pixel walk."""
    render_layers = prepare_scene(scene)
    viewport = viewport_aabb(width, height)
    tree = build_quadtree(render_layers, viewport, max_depth=max_depth)
    leaf_layers = _iter_leaf_layers(tree)
    surface = ArraySurface(width, height, fill=TRANSPARENT)
    layer_op_ids, shape_objects, program_op_ids = _register_render_vm(
        width,
        height,
        render_layers,
        extra_layers=leaf_layers,
    )
    tree = _finalize_paint_op_ids(tree, layer_op_ids, program_op_ids)
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
