# fmt: off
"""simpletest: one centered circle in a 512x512 viewport."""

from __future__ import annotations

import array

from imgcomp.naive import NaiveCompositor
from imgcomp.rgba import TRANSPARENT
from imgcomp.scene import Scene, as_z_list
from imgcomp.shapes import Circle
from imgcomp.surface import ArraySurface, Surface
from tests import _simpletest_c as _st


VIEWPORT = 512
CIRCLE_RADIUS = 200.4


def simpletest_scene() -> list[Circle]:
    """Scene under test: a single centered white circle."""
    return [Circle(CIRCLE_RADIUS)]


def circle_radius_from_scene(scene: Scene) -> float:
    """Return the radius of the first Circle in the scene."""
    for shape in as_z_list(scene):
        if isinstance(shape, Circle):
            return shape.radius
    raise ValueError("scene must contain a Circle")


def render_python(scene: Scene, width: int, height: int) -> Surface:
    """Render via NaiveCompositor (reference path)."""
    return NaiveCompositor(width, height).render(scene)


def render_stacklang(scene: Scene, width: int, height: int) -> Surface:
    """Render using the stacklang path."""
    from imgcomp.stacklang_render import render

    return render(scene, width, height)


def render_c(scene: Scene, width: int, height: int) -> Surface:
    """Render in native C without the stack VM."""
    radius = circle_radius_from_scene(scene)
    raw = _st.render_circle_native(width, height, radius)
    surface = ArraySurface(width, height, fill=TRANSPARENT)
    surface.pixel_buffer()[:] = array.array("B", raw)
    return surface


def surface_white_count(surface: Surface) -> int:
    """Count opaque white pixels (alpha 255)."""
    return int(_st.white_pixel_count(surface.to_bytes(), surface.width, surface.height))
