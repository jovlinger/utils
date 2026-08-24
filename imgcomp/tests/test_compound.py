"""Tests for filled SDF compound objects."""

from __future__ import annotations

from imgcomp.compound import Fatten, Intersect, StretchShape, Subtract, Thin, Union
from imgcomp.naive import NaiveCompositor
from imgcomp.shapes import Circle, Rectangle
from imgcomp.wrappers import Color, Stretch


def test_union_renders_both_regions_one_color() -> None:
    comp = NaiveCompositor(20, 10)
    shape = Color(
        Union(Circle(2.0), Rectangle(4.0, 1.0)),
        (0, 0, 255, 255),
    )
    surface = comp.render([shape])
    assert surface.get_pixel(10, 5) == (0, 0, 255, 255)
    assert surface.get_pixel(13, 5) == (0, 0, 255, 255)


def test_subtract_carves_hole_from_rectangle() -> None:
    comp = NaiveCompositor(20, 20)
    shape = Color(Subtract(Rectangle(6.0, 4.0), Circle(2.0)), (255, 0, 0, 255))
    surface = comp.render([shape])
    assert surface.get_pixel(10, 10) == (0, 0, 0, 0)
    assert surface.get_pixel(15, 10) == (255, 0, 0, 255)


def test_intersect_keeps_overlap_only() -> None:
    comp = NaiveCompositor(20, 20)
    shape = Color(
        Intersect(Circle(5.0), Rectangle(3.0, 3.0)),
        (255, 255, 0, 255),
    )
    surface = comp.render([shape])
    assert surface.get_pixel(10, 10) == (255, 255, 0, 255)
    assert surface.get_pixel(14, 10) == (0, 0, 0, 0)


def test_fatten_expands_rendered_shape() -> None:
    comp = NaiveCompositor(20, 20)
    thin = Color(Circle(2.0), (255, 0, 0, 255))
    fat = Color(Fatten(Circle(2.0), 2.0), (255, 0, 0, 255))
    thin_surface = comp.render([thin])
    fat_surface = comp.render([fat])
    assert thin_surface.get_pixel(12, 10) == (0, 0, 0, 0)
    assert fat_surface.get_pixel(12, 10) == (255, 0, 0, 255)


def test_thin_shrinks_rendered_shape() -> None:
    comp = NaiveCompositor(20, 20)
    base = Color(Circle(4.0), (255, 0, 0, 255))
    shrunk = Color(Thin(Circle(4.0), 2.0), (255, 0, 0, 255))
    base_surface = comp.render([base])
    thin_surface = comp.render([shrunk])
    assert base_surface.get_pixel(13, 10) == (255, 0, 0, 255)
    assert thin_surface.get_pixel(13, 10) == (0, 0, 0, 0)


def test_stretch_shape_and_wrapper_both_elongate() -> None:
    comp = NaiveCompositor(30, 20)
    sdf_shape = Color(StretchShape(Circle(2.0), 3.0, 1.0), (255, 0, 0, 255))
    wrapper_shape = Color(Stretch(Circle(2.0), 3.0, 1.0), (0, 255, 0, 255))
    sdf_surface = comp.render([sdf_shape])
    wrap_surface = comp.render([wrapper_shape])
    assert sdf_surface.get_pixel(16, 10) == (255, 0, 0, 255)
    assert wrap_surface.get_pixel(16, 10) == (0, 255, 0, 255)
