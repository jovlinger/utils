"""Tests for affine-aware bounds and compound maybe_intersect_rect."""

from __future__ import annotations

from imgcomp.compound import Intersect, Subtract, Union, ZList
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


def test_union_intersected_by_keeps_only_overlapping_members() -> None:
    gap = AABB(-1.0, -1.0, 1.0, 1.0)
    shape = Union(
        Circle(2.0).translate(-8.0, 0.0),
        Circle(2.0).translate(8.0, 0.0),
    )
    culled = shape.intersected_by(gap)
    assert culled is None


def test_union_cachekey_matches_content_key() -> None:
    from imgcomp.content_key import content_key

    shape = Union(
        Circle(2.0).translate(-8.0, 0.0),
        Circle(2.0).translate(8.0, 0.0),
    )
    assert shape.cachekey() == content_key(shape)


def test_quadtree_interns_identical_zlists() -> None:
    from imgcomp.stacklang_render import build_quadtree, prepare_scene, viewport_aabb
    from tests.fractal_scenes import fractal_gallery_scene

    layers = prepare_scene(fractal_gallery_scene("spirograph", size=192, profile="fast"))
    tree = build_quadtree(layers, viewport_aabb(192, 192))

    zlists: list[ZList] = []

    def walk(node) -> None:
        if node.zlist is not None:
            zlists.append(node.zlist)
            return
        assert node.children is not None
        for child in node.children:
            walk(child)

    walk(tree)
    assert len(zlists) > 1
    unique = {id(zlist) for zlist in zlists}
    assert len(unique) < len(zlists)


def test_intersect_maybe_intersect_needs_both_operands() -> None:
    query = AABB(3.5, -0.5, 4.5, 0.5)
    shape = Intersect(Circle(5.0), Rectangle(3.0, 3.0))
    assert not shape.maybe_intersect_rect(query)
    assert not shape.AABB().intersects(query)


def test_subtract_maybe_intersect_ignores_right_operand_extent() -> None:
    query = AABB(-1.0, -1.0, 1.0, 1.0)
    shape = Subtract(Circle(2.0).translate(10.0, 0.0), Circle(1.0))
    assert not shape.maybe_intersect_rect(query)
