"""Gallery tests: render fractal scenes and verify visual structure."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from imgcomp import NaiveCompositor
from tests.fractal_scenes import GALLERY_BACKGROUND, fractal_gallery_scene


def _load_rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


def _nontransparent_pixels(image: Image.Image) -> int:
    _, _, _, alpha = image.split()
    histogram = alpha.histogram()
    return sum(count for value, count in enumerate(histogram) if value > 0)


def _foreground_pixels(image: Image.Image, *, background: RGBA = GALLERY_BACKGROUND) -> list[tuple[int, int, int]]:
    rgb = image.convert("RGB")
    if not (loaded := rgb.load()):
        return []
    pixels: list[tuple[int, int, int]] = []
    bg = background[:3]
    for y in range(rgb.height):
        for x in range(rgb.width):
            pixel = loaded[x, y]
            if pixel != bg:
                pixels.append(pixel)
    return pixels


def _color_channel_stddev(image: Image.Image, *, background: RGBA = GALLERY_BACKGROUND) -> float:
    pixels = _foreground_pixels(image, background=background)
    if len(pixels) < 16:
        return 0.0
    channels = ([pixel[0] for pixel in pixels], [pixel[1] for pixel in pixels], [pixel[2] for pixel in pixels])
    stddevs: list[float] = []
    for channel in channels:
        mean = sum(channel) / len(channel)
        variance = sum((value - mean) ** 2 for value in channel) / len(channel)
        stddevs.append(variance**0.5)
    return sum(stddevs) / len(stddevs)


@pytest.mark.parametrize("kind", ["carpet", "phyllotaxis", "rings", "spirograph"])
def test_fractal_gallery_renders_rich_png(tmp_path: Path, kind: str) -> None:
    size = 192
    comp = NaiveCompositor(size, size)
    scene = fractal_gallery_scene(kind, size=size, profile="fast")
    out = tmp_path / f"{kind}.png"
    comp.render_png(scene, out)

    image = _load_rgba(out)
    assert image.size == (size, size)
    foreground = _foreground_pixels(image)
    distinct_colors = len(set(foreground))
    min_foreground = {
        "carpet": size * size // 6,
        "phyllotaxis": 18,
        "rings": size * size // 10,
        "spirograph": 400,
    }
    assert len(foreground) > min_foreground[kind]
    if kind == "carpet":
        assert (235, 210, 145) in set(foreground)
    elif kind == "phyllotaxis":
        assert distinct_colors >= 4
        assert _color_channel_stddev(image) > 8.0
    else:
        assert distinct_colors >= 8
        assert _color_channel_stddev(image) > 12.0


def test_sierpinski_carpet_keeps_center_hole(tmp_path: Path) -> None:
    size = 192
    comp = NaiveCompositor(size, size)
    scene = fractal_gallery_scene("carpet", size=size, profile="fast")
    out = tmp_path / "carpet_center.png"
    comp.render_png(scene, out)
    image = _load_rgba(out)
    center = image.getpixel((size // 2, size // 2))
    corner = image.getpixel((size // 8, size // 8))
    assert center[:3] == GALLERY_BACKGROUND[:3]
    assert corner[0] > 180 and corner[1] > 150
