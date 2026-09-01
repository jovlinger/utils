# fmt: off
"""simpletest: one centered circle in a 512x512 viewport."""

from __future__ import annotations

from imgcomp.naive import render_quadtree_python
from imgcomp.scene import Scene
from imgcomp.shapes import Circle
from imgcomp.surface import Surface
from tests import _simpletest_c as _st


VIEWPORT = 512
CIRCLE_RADIUS = 200.4


def simpletest_scene() -> list[Circle]:
    """Scene under test: a single centered white circle."""
    return [Circle(CIRCLE_RADIUS)]


def render_python(scene: Scene, width: int, height: int, *, min_size: float = 16.0) -> Surface:
    """Render via quadtree leaf-cell batch (pure Python reference path)."""
    return render_quadtree_python(scene, width, height, min_size=min_size)


def render_stacklang(scene: Scene, width: int, height: int, *, min_size: float = 16.0) -> Surface:
    """Render using the stacklang path (tests only; not bench_render on master)."""
    from imgcomp.stacklang_render import render

    return render(scene, width, height, min_size=min_size)


def surface_white_count(surface: Surface) -> int:
    """Count opaque white pixels (alpha 255)."""
    return int(_st.white_pixel_count(surface.to_bytes(), surface.width, surface.height))
