"""Tests for affine-aware bounds and compound maybe_intersect_rect."""

from __future__ import annotations

from imgcomp.compound import Intersect, Subtract, Union
from imgcomp.shape import AABB
from imgcomp.shapes import Circle, Rectangle
from imgcomp.wrappers import Rotate


def test_rotated_bounds_tighter_than_aabb_envelope() -> None:
    shape = Rotate(Rectangle(5.0, 1.0), 45.0)
    query = AABB(3.5, -0.5, 4.5, 0.5)
    assert shape.AABB().intersects(query)
    assert not shape.bounds().intersects_aabb(query)


def test_union_maybe_intersect_skips_gap_between_members() -> None:
    gap = AABB(-1.0, -1.0, 1.0, 1.0)
    shape = Union(
        Circle(2.0).translate(-8.0, 0.0),
        Circle(2.0).translate(8.0, 0.0),
    )
    assert shape.AABB().intersects(gap)
    assert not shape.maybe_intersect_rect(gap)


def test_intersect_maybe_intersect_needs_both_operands() -> None:
    query = AABB(3.5, -0.5, 4.5, 0.5)
    shape = Intersect(Circle(5.0), Rectangle(3.0, 3.0))
    assert not shape.maybe_intersect_rect(query)
    assert not shape.AABB().intersects(query)


def test_subtract_maybe_intersect_ignores_right_operand_extent() -> None:
    query = AABB(-1.0, -1.0, 1.0, 1.0)
    shape = Subtract(Circle(2.0).translate(10.0, 0.0), Circle(1.0))
    assert not shape.maybe_intersect_rect(query)
