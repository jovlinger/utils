"""Tests for scene list roots and shared geometry references."""

from __future__ import annotations

from imgcomp import Circle, Color, NaiveCompositor, Translate, WHITE


def test_scene_accepts_z_ordered_list() -> None:
    comp = NaiveCompositor(20, 20)
    scene = [
        Color(Circle(3.0), (255, 0, 0, 255)),
        Color(Circle(2.0), (0, 255, 0, 255)),
    ]
    surface = comp.render(scene)
    assert surface.get_pixel(10, 10) == (0, 255, 0, 255)


def test_shared_geometry_referenced_from_multiple_places() -> None:
    comp = NaiveCompositor(200, 200)
    shared = Circle(50.0)
    scene = [
        Color(Translate(shared, 50.0, 50.0), (255, 0, 0, 255)),
        Color(Translate(shared, -50.0, -50.0), (0, 0, 255, 255)),
    ]
    surface = comp.render(scene)
    assert surface.get_pixel(150, 150) == (255, 0, 0, 255)
    assert surface.get_pixel(50, 50) == (0, 0, 255, 255)
    assert shared.color_at(0.0, 0.0) == WHITE
