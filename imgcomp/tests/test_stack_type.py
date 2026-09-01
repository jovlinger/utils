"""StackType / PrePost Chuck Moore-style stack annotations."""

from __future__ import annotations

import pytest

from imgcomp import stack_c as sc
from imgcomp.stack_type import PrePost, StackType, flatten_authoring, set_stack_type_debug
from tests.fractal_scenes import fractal_gallery_scene
from tests.bench_render import GALLERY_PROFILE, GALLERY_SIZE
from tests.simpletest import render_stacklang


def test_stack_type_effect_str() -> None:
    st = StackType(pre=("x", "y"), post=("area",))
    assert st.effect_str() == "( x y -- area )"


def test_prepost_repr_area() -> None:
    sc.reset_vm()
    sc.register_base_ops()
    area = PrePost([sc.f_mul], pre=["x", "y"], post=["area"], label="area")
    assert repr(area) == "PrePost( x y -- area ) 'area'"


def test_prepost_flatten_debug_off_is_noop() -> None:
    set_stack_type_debug(False)
    sc.reset_vm()
    sc.register_base_ops()
    area = PrePost([sc.f_mul], pre=["x", "y"], post=["area"], label="area")
    assert flatten_authoring([area]) == [sc.f_mul]


def test_prepost_flatten_debug_on_emits_check_ops() -> None:
    set_stack_type_debug(True)
    try:
        sc.reset_vm()
        sc.register_base_ops()
        area = PrePost([sc.f_mul], pre=["x", "y"], post=["area"], label="area")
        flat = flatten_authoring([area])
        assert len(flat) == 3
        assert flat[1] is sc.f_mul
        assert flat[0].name.startswith("__stack_pre_")
        assert flat[2].name.startswith("__stack_post_")
    finally:
        set_stack_type_debug(False)


def test_area_debug_catches_wrong_pre_height() -> None:
    set_stack_type_debug(True)
    try:
        sc.reset_vm()
        sc.register_base_ops()
        area = PrePost([], pre=["x", "y"], post=["area"], label="area")
        sc.register_op("area", area)
        with pytest.raises(RuntimeError, match="area.*pre-check"):
            sc.eval_op("area")
    finally:
        set_stack_type_debug(False)


def test_union_spirograph_stack_debug_renders() -> None:
    set_stack_type_debug(True)
    try:
        scene = fractal_gallery_scene("spirograph", size=GALLERY_SIZE, profile=GALLERY_PROFILE)
        surface = render_stacklang(scene, GALLERY_SIZE, GALLERY_SIZE)
        assert surface.width == GALLERY_SIZE
        assert surface.height == GALLERY_SIZE
    finally:
        set_stack_type_debug(False)


def test_if_branch_selects_true_or_false_body() -> None:
    sc.reset_vm()
    sc.register_base_ops()
    true_body = sc.register_op("if_true", [1, sc.i_add])
    false_body = sc.register_op("if_false", [2, sc.i_add])
    sc.register_op(
        "if_prog",
        [
            10,
            1,
            sc.lit_op,
            true_body,
            sc.lit_op,
            false_body,
            sc.if_,
        ],
    )
    sc.eval_op("if_prog")
    from imgcomp import _stack_c as _cy

    assert _cy.pop_int() == 11

    sc.reset_vm()
    sc.register_base_ops()
    true_body = sc.register_op("if_true", [1, sc.i_add])
    false_body = sc.register_op("if_false", [2, sc.i_add])
    sc.register_op(
        "if_prog",
        [
            10,
            0,
            sc.lit_op,
            true_body,
            sc.lit_op,
            false_body,
            sc.if_,
        ],
    )
    sc.eval_op("if_prog")
    assert _cy.pop_int() == 12


def test_area_debug_passes_valid_body() -> None:
    set_stack_type_debug(True)
    try:
        sc.reset_vm()
        sc.register_base_ops()
        area = PrePost([sc.f_mul], pre=["x", "y"], post=["area"], label="area")
        sc.register_op(
            "area_prog",
            [3.0, 4.0, area],
        )
        sc.eval_op("area_prog")
        from imgcomp import _stack_c as _cy

        assert sc.get_data_sp() == 1
        assert _cy.pop_float() == pytest.approx(12.0)
    finally:
        set_stack_type_debug(False)
