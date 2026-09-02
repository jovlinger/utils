"""Stacklang render: surf shape graph, quadtree z-lists, stacklang pixel walk."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Hashable

from imgcomp import _stacklang_render_c as _slr
from imgcomp import stack_c as sc
from imgcomp.compound import Union, ZList
from imgcomp.intersect_cache import cached_intersected_by, intersect_cache_session
from imgcomp.rgba import RGBA, TRANSPARENT, src_over
from imgcomp.scene import Scene, as_z_list
from imgcomp.shape import AABB, Bounds, Shape, StackLangBody
from imgcomp.surface import ArraySurface, Surface
from imgcomp.shapes import set_using_stacklang
from imgcomp.stack_type import PrePost, flatten_authoring, strip_prepost
from imgcomp.stacklang_debug import log_py_to_c

from imgcomp.quadtree_blob import mmap_quadtree, serialize_quadtree


@dataclass(frozen=True)
class SceneLayer:
    """One scene z-layer root and its color_at stacklang program."""

    index: int
    shape: Shape
    color_stacklang: StackLangBody


@dataclass(frozen=True)
class QuadNode:
    """Quadtree node: either a leaf ZList bucket or four children."""

    bounds: AABB
    zlist: ZList | None = None
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


def prepare_shape_layers(scene: Scene) -> list[SceneLayer]:
    """Scene layer roots for quadtree culling (no stacklang export)."""
    return [
        SceneLayer(index=layer_index, shape=layer_shape, color_stacklang=[])
        for layer_index, layer_shape in enumerate(as_z_list(scene))
    ]


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
    """Intern culled ZList shapes for identical quadtree cells."""

    _zlists: dict[tuple[tuple[Hashable, ...], ...], ZList] = field(default_factory=dict)

    def zlist_for_bounds(
        self, layers: Sequence[SceneLayer], bounds: AABB
    ) -> ZList | None:
        members: list[Shape] = []
        for layer in layers:
            culled_shape = cached_intersected_by(layer.shape, bounds)
            if culled_shape is not None:
                members.append(culled_shape)
        if not members:
            return None
        zlist_key = tuple(member.cachekey() for member in members)
        cached = self._zlists.get(zlist_key)
        if cached is not None:
            return cached
        cached = ZList(*members)
        self._zlists[zlist_key] = cached
        return cached


def _max_union_members(zlist: ZList) -> int:
    """Largest Union arity among z-list layer roots (0 if none)."""
    count = 0
    for shape in zlist.members:
        if isinstance(shape, Union):
            count = max(count, len(shape.members))
    return count


def build_quadtree(
    layers: Sequence[SceneLayer],
    bounds: AABB,
    *,
    max_depth: int = 8,
    max_per_leaf: int = 4,
    min_size: float = 16.0,
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
    here = intern.zlist_for_bounds(layers, bounds)
    if here is None:
        return QuadNode(bounds=bounds, zlist=ZList())
    width = bounds.xmax - bounds.xmin
    height = bounds.ymax - bounds.ymin
    heavy_union = _max_union_members(here) > max_per_leaf
    if (
        max_depth <= 0
        or (len(here.members) <= max_per_leaf and not heavy_union)
        or width <= min_size
        or height <= min_size
    ):
        return QuadNode(bounds=bounds, zlist=here)

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
            build_quadtree(layers, nw, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
            build_quadtree(layers, ne, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
            build_quadtree(layers, sw, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
            build_quadtree(layers, se, max_depth=child_depth, max_per_leaf=max_per_leaf, min_size=min_size, intern=intern),
        ),
    )


def z_list_at_point(node: QuadNode, gx: float, gy: float) -> ZList | None:
    """Return culled z-list shape at a global point."""
    if node.zlist is not None:
        return node.zlist
    assert node.children is not None
    for child in node.children:
        if (
            child.bounds.xmin <= gx <= child.bounds.xmax
            and child.bounds.ymin <= gy <= child.bounds.ymax
        ):
            return z_list_at_point(child, gx, gy)
    return None


def _iter_leaf_zlists(node: QuadNode) -> list[ZList]:
    if node.zlist is not None:
        return [node.zlist]
    assert node.children is not None
    leaves: list[ZList] = []
    for child in node.children:
        leaves.extend(_iter_leaf_zlists(child))
    return leaves


def _iter_leaf_nodes(node: QuadNode) -> list[QuadNode]:
    """Return every quadtree leaf node (zlist bucket with bounds)."""
    if node.zlist is not None:
        return [node]
    assert node.children is not None
    leaves: list[QuadNode] = []
    for child in node.children:
        leaves.extend(_iter_leaf_nodes(child))
    return leaves


def _unique_members(zlists: Sequence[ZList]) -> list[Shape]:
    members: list[Shape] = []
    seen: set[tuple[Hashable, ...]] = set()
    for zlist in zlists:
        for member in zlist.members:
            key = member.cachekey()
            if key in seen:
                continue
            seen.add(key)
            members.append(member)
    return members


def color_at_layer(layer: SceneLayer, gx: float, gy: float) -> RGBA | None:
    """Reference color_at for a full layer root in scene space."""
    return layer.shape.color_at(gx, gy)


def accumulate_layers(
    layers: Sequence[SceneLayer],
    z_list: ZList,
    gx: float,
    gy: float,
) -> RGBA:
    """Composite scene layers back-to-front (reference path)."""
    return z_list.color_at(gx, gy) or TRANSPARENT


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
        if isinstance(token, ZList):
            raise NotImplementedError("ZList VM compositing is handled in C")
        if isinstance(token, sc.OpHandler):
            body.append(token)
            index += 1
            continue
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
    zlists: Sequence[ZList],
) -> tuple[dict[tuple[Hashable, ...], int], list[Shape]]:
    """Register per-member shape color_at VM bodies."""
    sc.reset_vm()
    sc.register_base_ops()
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

    vm_kwargs = dict(
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
    shape_objects: list[Shape] = []
    member_op_ids: dict[tuple[Hashable, ...], int] = {}
    for member_index, member in enumerate(_unique_members(zlists)):
        key = member.cachekey()
        if key in member_op_ids:
            continue
        body = _vm_body(
            member.color_at_stacklang(),
            owner=member,
            shape_objects=shape_objects,
            **vm_kwargs,
        )
        member_op_ids[key] = sc.register_op(f"member_{member_index}", body).op_id

    return member_op_ids, shape_objects


def render(
    scene: Scene,
    width: int,
    height: int,
    *,
    max_depth: int = 8,
    min_size: float = 16.0,
) -> Surface:
    """Stacklang render: surf graph, quadtree z-lists, C leaf-cell batch paint."""
    render_layers = prepare_scene(scene)
    viewport = viewport_aabb(width, height)
    tree = build_quadtree(render_layers, viewport, max_depth=max_depth, min_size=min_size)
    leaf_zlists = _iter_leaf_zlists(tree)
    unique_zlists: list[ZList] = []
    seen: set[tuple[Hashable, ...]] = set()
    for zlist in leaf_zlists:
        key = zlist.cachekey()
        if key in seen:
            continue
        seen.add(key)
        unique_zlists.append(zlist)
    surface = ArraySurface(width, height, fill=TRANSPARENT)
    member_op_ids, shape_objects = _register_render_vm(width, height, unique_zlists)
    quadtree_mm = mmap_quadtree(
        serialize_quadtree(tree, member_op_ids=member_op_ids)
    )
    _slr.bind_render(
        surface.pixel_buffer(),
        width,
        height,
        quadtree_mm,
        shape_objects,
    )
    log_py_to_c("render_quadtree", width=width, height=height, layers=len(render_layers))
    set_using_stacklang(True)
    try:
        _slr.render_quadtree()
    finally:
        set_using_stacklang(False)
    log_py_to_c("render_quadtree_return", width=width, height=height)
    return surface
