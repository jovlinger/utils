"""Tests for offline PNG export."""

from __future__ import annotations

from pathlib import Path

from imgcomp.export import render_png
from imgcomp.naive import NaiveCompositor
from imgcomp.primitives import Circle
from imgcomp.wrappers import Group
from PIL import Image


def test_render_png_round_trip(tmp_path: Path) -> None:
    comp = NaiveCompositor(6, 6)
    scene = Group((Circle(2.0, (255, 128, 64, 255)),))
    out = tmp_path / "markup.png"
    render_png(comp, scene, out)
    image = Image.open(out)
    assert image.size == (6, 6)
    assert image.getpixel((3, 3)) == (255, 128, 64, 255)
