"""Tests for SDF combinators."""

from __future__ import annotations

from imgcomp.sdf import (
    CircleSDF,
    IntersectSDF,
    OffsetSDF,
    RectangleSDF,
    RotateSDF,
    StretchSDF,
    SubtractSDF,
    UnionSDF,
)


def test_union_is_inside_when_either_child_is_inside() -> None:
    field = UnionSDF(CircleSDF(2.0), RectangleSDF(5.0, 1.0))
    assert field.distance(0.0, 0.0) <= 0.0
    assert field.distance(4.0, 0.0) <= 0.0
    assert field.distance(6.0, 0.0) > 0.0


def test_intersect_requires_both_children() -> None:
    field = IntersectSDF(CircleSDF(4.0), RectangleSDF(2.0, 2.0))
    assert field.distance(0.0, 0.0) <= 0.0
    assert field.distance(3.0, 0.0) > 0.0


def test_subtract_removes_right_shape() -> None:
    field = SubtractSDF(RectangleSDF(4.0, 4.0), CircleSDF(2.0))
    assert field.distance(3.0, 0.0) <= 0.0
    assert field.distance(0.0, 0.0) > 0.0


def test_fatten_moves_boundary_outward() -> None:
    inner = CircleSDF(2.0)
    outer = OffsetSDF(inner, 1.0)
    assert inner.distance(2.0, 0.0) <= 0.0
    assert outer.distance(2.0, 0.0) <= 0.0
    assert outer.distance(3.0, 0.0) <= 0.0
    assert outer.distance(3.1, 0.0) > 0.0


def test_thin_moves_boundary_inward() -> None:
    inner = CircleSDF(3.0)
    shrunk = OffsetSDF(inner, -1.0)
    assert inner.distance(2.5, 0.0) <= 0.0
    assert shrunk.distance(2.5, 0.0) > 0.0
    assert shrunk.distance(1.9, 0.0) <= 0.0


def test_rotate_sdf_spins_query_points() -> None:
    bar = RectangleSDF(4.0, 1.0)
    rotated = RotateSDF(bar, 90.0)
    assert bar.distance(3.0, 0.0) <= 0.0
    assert rotated.distance(0.0, 3.0) <= 0.0


def test_stretch_sdf_scales_query_points() -> None:
    disk = CircleSDF(2.0)
    stretched = StretchSDF(disk, 2.0, 1.0)
    assert stretched.distance(3.9, 0.0) <= 0.0
    assert disk.distance(3.9, 0.0) > 0.0
