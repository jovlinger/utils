"""Minimal v0 learner-facing constructors for the visual REPL."""

from __future__ import annotations

from imgcomp.shape import Shape
from imgcomp.rgba import RGBA
from imgcomp.shapes import Circle, Oval, Rectangle
from imgcomp.wrappers import Color, Rotate, Stretch, Translate


def circle(radius: float) -> Circle:
    return Circle(radius)


def rect(half_width: float, half_height: float) -> Rectangle:
    return Rectangle(half_width, half_height)


def oval(radius_x: float, radius_y: float) -> Oval:
    return Oval(radius_x, radius_y)


def color(shape: Shape, r: int, g: int, b: int, a: int = 255) -> Color:
    rgba: RGBA = (r, g, b, a)
    return Color(shape, rgba)


def move(shape: Shape, x: float, y: float) -> Translate:
    return Translate(shape, x, y)


def turn(shape: Shape, degrees: float) -> Rotate:
    return Rotate(shape, degrees)


def stretch(shape: Shape, scale_x: float, scale_y: float) -> Stretch:
    return Stretch(shape, scale_x, scale_y)


def api_namespace() -> dict[str, object]:
    """Return a fresh dict of v0 callables for exec/eval."""
    return {
        "circle": circle,
        "rect": rect,
        "oval": oval,
        "color": color,
        "move": move,
        "turn": turn,
        "stretch": stretch,
    }
