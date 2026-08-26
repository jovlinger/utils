"""Structured 2D compositor for image markup."""

from imgcomp.compound import (
    Fatten,
    Intersect,
    RotateShape,
    StretchShape,
    Subtract,
    Thin,
    Union,
    fatten,
    intersect,
    rotate,
    stretch,
    subtract,
    thin,
    union,
)
from imgcomp.compositor import Compositor
from imgcomp.content_key import content_key
from imgcomp.naive import NaiveCompositor
from imgcomp.quad_cache import QuadCache
from imgcomp.shape import Shape
from imgcomp.primitives import ImageObject
from imgcomp.rgba import RGBA, TRANSPARENT, WHITE, src_over
from imgcomp.scene import Scene, as_scene, as_z_list
from imgcomp.shapes import Circle, Infinite, Oval, Rectangle, SDFShape
from imgcomp.surface import ArraySurface, Surface
from imgcomp.wrappers import Color, ColorMod, Rotate, Stretch, Translate

__all__ = [
    "ArraySurface",
    "Circle",
    "Color",
    "ColorMod",
    "Compositor",
    "Fatten",
    "Intersect",
    "Infinite",
    "ImageObject",
    "NaiveCompositor",
    "QuadCache",
    "Shape",
    "Oval",
    "RGBA",
    "Rectangle",
    "Rotate",
    "RotateShape",
    "Scene",
    "SDFShape",
    "Stretch",
    "StretchShape",
    "Subtract",
    "Surface",
    "Thin",
    "TRANSPARENT",
    "Translate",
    "Union",
    "WHITE",
    "as_scene",
    "as_z_list",
    "content_key",
    "fatten",
    "intersect",
    "rotate",
    "src_over",
    "stretch",
    "subtract",
    "thin",
    "union",
]
