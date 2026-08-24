"""Offline PNG export."""

from __future__ import annotations

from pathlib import Path

from imgcomp.object import Object
from imgcomp.compositor import Compositor
from imgcomp.surface import Surface


def surface_to_png(surface: Surface, path: Path | str) -> None:
    """Write a straight RGBA surface to PNG."""
    from PIL import Image

    image = Image.frombytes(
        "RGBA",
        (surface.width, surface.height),
        _surface_bytes(surface),
    )
    image.save(path)


def render_png(compositor: Compositor, root: Object, path: Path | str) -> None:
    """Render root at full compositor resolution and write PNG."""
    surface_to_png(compositor.render(root), path)


def _surface_bytes(surface: Surface) -> bytes:
    if hasattr(surface, "to_bytes"):
        return surface.to_bytes()  # type: ignore[attr-defined]
    rows = bytearray()
    for _x, _y, color in surface.iter_pixels():
        rows.extend(color)
    return bytes(rows)
