"""End-to-end acceptance test for image markup flow.

Happy path:
  Build a small markup scene (bitmap underlay + translated circle overlay),
  render it headlessly at full viewport resolution, export PNG, and verify
  both composite pixels and pick/dispatch on the overlay.
"""

from __future__ import annotations

from pathlib import Path

from imgcomp.export import render_png
from imgcomp.naive import NaiveCompositor
from imgcomp.primitives import Circle, ImageObject
from imgcomp.wrappers import Group, Translate
from PIL import Image


class MarkupHandle(Circle):
    def __init__(self, radius: float, color: tuple[int, int, int, int]) -> None:
        super().__init__(radius, color)
        self.touches: list[tuple[float, float]] = []

    def on_touch(self, x: float, y: float) -> None:
        self.touches.append((round(x, 3), round(y, 3)))


def test_markup_scene_exports_and_dispatches(tmp_path: Path) -> None:
    underlay = ImageObject.from_rgba_rows(
        [
            [(40, 40, 40, 255), (40, 40, 40, 255)],
            [(40, 40, 40, 255), (40, 40, 40, 255)],
        ]
    )
    handle = MarkupHandle(1.0, (255, 0, 0, 255))
    scene = Group((underlay, Translate(handle, 1.0, 0.0)))
    comp = NaiveCompositor(4, 4)

    out = tmp_path / "markup.png"
    render_png(comp, scene, out)
    saved = Image.open(out)
    assert saved.size == (4, 4)
    assert saved.getpixel((3, 2)) == (255, 0, 0, 255)
    assert saved.getpixel((1, 2)) == (40, 40, 40, 255)

    assert comp.dispatch_event(scene, "touch", 3.0, 2.0) is True
    assert handle.touches == [(0.0, 0.0)]
