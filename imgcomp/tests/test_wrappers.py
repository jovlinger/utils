"""Tests for wrapper transforms."""

from __future__ import annotations

from imgcomp.naive import NaiveCompositor
from imgcomp.primitives import Circle
from imgcomp.wrappers import ColorMod, Group, Rotate, Translate


def test_translate_moves_visible_disk() -> None:
    comp = NaiveCompositor(20, 20)
    scene = Group((Translate(Circle(2.0, (255, 0, 0, 255)), 5.0, 0.0),))
    surface = comp.render(scene)
    assert surface.get_pixel(15, 10) == (255, 0, 0, 255)
    assert surface.get_pixel(10, 10) == (0, 0, 0, 0)


def test_color_mod_multiplies_channels() -> None:
    comp = NaiveCompositor(10, 10)
    scene = Group((ColorMod(Circle(3.0, (200, 100, 50, 255)), r_mul=0.5, g_mul=1.0, b_mul=1.0, a_mul=1.0),))
    surface = comp.render(scene)
    red, green, blue, alpha = surface.get_pixel(5, 5)
    assert red == 100
    assert green == 100
    assert blue == 50
    assert alpha == 255


def test_rotate_wrapper_forwards_pick_at_center() -> None:
    comp = NaiveCompositor(20, 20)
    target = Circle(2.0, (255, 255, 255, 255))
    scene = Group((Rotate(target, 90.0),))
    picked = comp.pick(scene, 10.0, 10.0)
    assert picked is not None
    assert picked.target is target
    assert picked.local_x == 0.0
    assert picked.local_y == 0.0
