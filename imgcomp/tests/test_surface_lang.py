"""Stacklang tokens on shapes (color_at_stacklang, distance_stacklang)."""

from __future__ import annotations

from imgcomp.compound import Intersect, Union
from imgcomp.shape import AABB
from imgcomp.shapes import Circle, Infinite, Oval, Rectangle, SDFShape
from imgcomp.stack_type import flatten_authoring, set_stack_type_debug
from imgcomp.stacklang_render import prepare_scene
from imgcomp.wrappers import Color


def test_color_wraps_child_color_at_stacklang() -> None:
    lang = Color(Circle(1.0), (255, 0, 0, 255)).color_at_stacklang()
    assert flatten_authoring(lang) == [
        "dup_xy",
        1.0,
        "circle_distance",
        "sdf_fill_white",
        255,
        0,
        0,
        255,
        "rgba_solid_if_hit",
    ]


def test_sdf_shape_distance_stacklang_defaults_to_python() -> None:
    class PlainSDF(SDFShape):
        def distance(self, x: float, y: float) -> float:
            return x

        def AABB(self) -> AABB:
            return AABB(-1.0, -1.0, 1.0, 1.0)

    assert PlainSDF().distance_stacklang() == [
        "call_python_method",
        "distance",
    ]


def test_rectangle_distance_stacklang_is_native() -> None:
    assert Rectangle(2.0, 3.0).distance_stacklang() == [
        2.0,
        3.0,
        "rectangle_distance",
    ]


def test_rectangle_color_at_stacklang_composes_from_distance_stacklang() -> None:
    assert flatten_authoring(Rectangle(2.0, 3.0).color_at_stacklang()) == [
        "dup_xy",
        2.0,
        3.0,
        "rectangle_distance",
        "sdf_fill_white",
    ]


def test_oval_distance_stacklang_is_native() -> None:
    assert Oval(5.0, 2.0).distance_stacklang() == [5.0, 2.0, "oval_distance"]


def test_infinite_color_at_stacklang_is_fill_white() -> None:
    assert flatten_authoring(Infinite().color_at_stacklang()) == ["fill_white"]


def test_circle_distance_stacklang_is_native() -> None:
    circle = Circle(4.0)
    assert circle.distance_stacklang() == [4.0, "circle_distance"]


def test_circle_color_at_stacklang_composes_from_distance_stacklang() -> None:
    circle = Circle(4.0)
    assert flatten_authoring(circle.color_at_stacklang()) == [
        "dup_xy",
        4.0,
        "circle_distance",
        "sdf_fill_white",
    ]


def test_prepare_scene_intersect_color_at_stacklang_is_native() -> None:
    scene = [Color(Intersect(Circle(5.0), Rectangle(3.0, 3.0)), (255, 255, 0, 255))]
    layers = prepare_scene(scene)
    assert flatten_authoring(layers[0].color_stacklang) == [
        "dup_xy",
        5.0,
        "circle_distance",
        "dup_anchor_push_xy",
        3.0,
        3.0,
        "rectangle_distance",
        "float_max2",
        "sdf_fill_white",
        255,
        255,
        0,
        255,
        "rgba_solid_if_hit",
    ]


def test_union_color_at_stacklang_composes_native_members() -> None:
    set_stack_type_debug(False)
    union = Union(Circle(1.0), Circle(2.0))
    assert flatten_authoring(union.color_at_stacklang()) == [
        "push_transparent_accum",
        "dup_anchor_xy",
        "dup_xy",
        2.0,
        "circle_distance",
        "sdf_fill_white",
        "drop_hit_xy",
        "src_over_layer",
        "dup_anchor_xy",
        "dup_xy",
        1.0,
        "circle_distance",
        "sdf_fill_white",
        "drop_hit_xy",
        "src_over_layer",
    ]


def test_union_layer_stacklang_composes_members() -> None:
    set_stack_type_debug(False)
    scene = [
        Union(
            Color(Circle(4.0), (255, 0, 0, 255)),
            Color(Circle(4.0), (0, 255, 0, 255)),
        )
    ]
    layers = prepare_scene(scene)
    assert isinstance(layers[0].shape, Union)
    assert flatten_authoring(layers[0].color_stacklang) == [
        "push_transparent_accum",
        "dup_anchor_xy",
        "dup_xy",
        4.0,
        "circle_distance",
        "sdf_fill_white",
        0,
        255,
        0,
        255,
        "rgba_solid_if_hit",
        "drop_hit_xy",
        "src_over_layer",
        "dup_anchor_xy",
        "dup_xy",
        4.0,
        "circle_distance",
        "sdf_fill_white",
        255,
        0,
        0,
        255,
        "rgba_solid_if_hit",
        "drop_hit_xy",
        "src_over_layer",
    ]
