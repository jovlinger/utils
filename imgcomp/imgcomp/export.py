"""Backward-compatible re-exports; prefer Compositor.render_png and Surface.write_png."""

from __future__ import annotations

from pathlib import Path

from imgcomp.compositor import Compositor
from imgcomp.scene import Scene
from imgcomp.surface import Surface


def surface_to_png(surface: Surface, path: Path | str) -> None:
    """Write a straight RGBA surface to PNG."""
    surface.write_png(path)


def render_png(compositor: Compositor, root: Scene, path: Path | str) -> None:
    """Render root at full compositor resolution and write PNG."""
    compositor.render_png(root, path)
