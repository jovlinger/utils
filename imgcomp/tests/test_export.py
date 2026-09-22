"""Tests for offline PNG export."""

from __future__ import annotations

from pathlib import Path

from imgcomp.naive import NaiveCompositor
from imgcomp.shapes import Circle
from imgcomp.wrappers import Color
from PIL import Image


def test_render_png_round_trip(tmp_path: Path) -> None:
    comp = NaiveCompositor(6, 6)
    scene = [Color(Circle(2.0), (255, 128, 64, 255))]
    out = tmp_path / "markup.png"
    comp.render_png(scene, out)
    image = Image.open(out)
    assert image.size == (6, 6)
    assert image.getpixel((3, 3)) == (255, 128, 64, 255)


def test_surface_write_png_matches_compositor_render_png(tmp_path: Path) -> None:
    comp = NaiveCompositor(4, 4)
    scene = [Color(Circle(1.0), (10, 20, 30, 255))]
    direct = tmp_path / "direct.png"
    via_comp = tmp_path / "via_comp.png"
    comp.render(scene).write_png(direct)
    comp.render_png(scene, via_comp)
    assert Image.open(direct).getpixel((2, 2)) == Image.open(via_comp).getpixel((2, 2))
