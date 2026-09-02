"""Render prep must not stamp VM op ids onto user-owned scene graph objects."""

from __future__ import annotations

import pytest

from tests.fractal_scenes import fractal_gallery_scene
from tests.simpletest import surface_white_count

GALLERY = 192
EXPECTED_RINGS_WHITE = 7_488


def _top_level_paint_op_ids(scene: list[object]) -> dict[int, int]:
    return {id(shape): getattr(shape, "paint_op_id", -1) for shape in scene}


def _branch_render():
    try:
        from imgcomp.render_directstack import render as directstack_render

        return directstack_render
    except ImportError:
        pass
    try:
        from imgcomp.stacklang_render import render as stacklang_render

        return stacklang_render
    except ImportError:
        pass
    try:
        from imgcomp.c_render import render as c_render

        return c_render
    except ImportError:
        pytest.skip("no render entrypoint on this branch")


def test_render_same_scene_twice_without_mutating_top_level_shapes() -> None:
    """Repeated renders must not write paint_op_id on scene layer roots."""
    scene = fractal_gallery_scene("rings", size=GALLERY, profile="fast")
    before = _top_level_paint_op_ids(scene)
    assert all(op_id == -1 for op_id in before.values())

    render = _branch_render()
    white_first = surface_white_count(render(scene, GALLERY, GALLERY, min_size=16.0))
    assert _top_level_paint_op_ids(scene) == before

    white_second = surface_white_count(render(scene, GALLERY, GALLERY, min_size=16.0))
    assert _top_level_paint_op_ids(scene) == before
    assert white_first == white_second == EXPECTED_RINGS_WHITE


def test_prepare_render_does_not_mutate_leaf_zlist_paint_op_id() -> None:
    """Quadtree leaf z-lists must keep default paint_op_id after prepare_render."""
    try:
        from imgcomp.render_prepare import prepare_render
        from imgcomp.stacklang_render import _iter_leaf_zlists
    except ImportError:
        pytest.skip("render_prepare not on this branch")

    scene = fractal_gallery_scene("rings", size=GALLERY, profile="fast")
    plan = prepare_render(scene, GALLERY, GALLERY, min_size=16.0)
    for zlist in _iter_leaf_zlists(plan.tree):
        assert zlist.paint_op_id == -1
