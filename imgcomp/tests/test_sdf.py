"""Tests for SDF combinators (distance on shape classes)."""

from __future__ import annotations

from imgcomp.compound import Intersect, Subtract, Union
from imgcomp.shapes import Circle, Rectangle
from imgcomp.compound import Fatten, RotateShape, StretchShape, Thin


def test_union_is_inside_when_either_child_is_inside() -> None:
    field = Union(Circle(2.0), Rectangle(5.0, 1.0))
    assert field.distance(0.0, 0.0) <= 0.0
    assert field.distance(4.0, 0.0) <= 0.0
    assert field.distance(6.0, 0.0) > 0.0


def test_intersect_requires_both_children() -> None:
    field = Intersect(Circle(4.0), Rectangle(2.0, 2.0))
    assert field.distance(0.0, 0.0) <= 0.0
    assert field.distance(3.0, 0.0) > 0.0


def test_subtract_removes_right_shape() -> None:
    field = Subtract(Rectangle(4.0, 4.0), Circle(2.0))
    assert field.distance(3.0, 0.0) <= 0.0
    assert field.distance(0.0, 0.0) > 0.0


def test_fatten_moves_boundary_outward() -> None:
    inner = Circle(2.0)
    outer = Fatten(inner, 1.0)
    assert inner.distance(2.0, 0.0) <= 0.0
    assert outer.distance(2.0, 0.0) <= 0.0
    assert outer.distance(3.0, 0.0) <= 0.0
    assert outer.distance(3.1, 0.0) > 0.0


def test_thin_moves_boundary_inward() -> None:
    inner = Circle(3.0)
    shrunk = Thin(inner, 1.0)
    assert inner.distance(2.5, 0.0) <= 0.0
    assert shrunk.distance(2.5, 0.0) > 0.0
    assert shrunk.distance(1.9, 0.0) <= 0.0


def test_rotate_shape_spins_query_points() -> None:
    bar = Rectangle(4.0, 1.0)
    rotated = RotateShape(bar, 90.0)
    assert bar.distance(3.0, 0.0) <= 0.0
    assert rotated.distance(0.0, 3.0) <= 0.0


def test_stretch_shape_scales_query_points() -> None:
    disk = Circle(2.0)
    stretched = StretchShape(disk, 2.0, 1.0)
    assert stretched.distance(3.9, 0.0) <= 0.0
    assert disk.distance(3.9, 0.0) > 0.0
