"""Scene preparation for stacklang render (graph surf, not flatten)."""

from __future__ import annotations

from imgcomp.compound import Intersect, Union
from imgcomp.shapes import Circle, Rectangle
from imgcomp.stacklang_render import prepare_scene
from imgcomp.stack_type import flatten_authoring
from imgcomp.wrappers import Color


def test_intersect_stays_one_layer_with_compound_root() -> None:
    scene = [Color(Intersect(Circle(5.0), Rectangle(3.0, 3.0)), (255, 255, 0, 255))]
    layers = prepare_scene(scene)
    assert len(layers) == 1
    assert isinstance(layers[0].shape, Color)
    assert isinstance(layers[0].shape.child, Intersect)
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


def test_union_and_top_layer_stay_separate_render_layers() -> None:
    scene = [
        Union(
            Color(Circle(4.0).translate(-6.0, 0.0), (255, 0, 0, 255)),
            Color(Circle(4.0).translate(6.0, 0.0), (0, 255, 0, 255)),
        ),
        Color(Circle(2.0), (0, 0, 255, 255)),
    ]
    layers = prepare_scene(scene)
    assert len(layers) == 2
    assert isinstance(layers[0].shape, Union)
    assert isinstance(layers[1].shape, Color)
    assert layers[0].index == 0
    assert layers[1].index == 1
