"""Flatten supported Shape trees into a Cython-friendly paint IR."""

from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Sequence

from imgcomp.compound import Subtract, Union
from imgcomp.rgba import RGBA
from imgcomp.shape import Shape
from imgcomp.shapes import Circle, Infinite, Rectangle
from imgcomp.wrappers import Color, Translate

KIND_INFINITE = 0
KIND_CIRCLE = 1
KIND_RECT = 2
KIND_RING = 3


@dataclass(frozen=True)
class FlatScene:
    """Packed sprites grouped into z-layers (index 0 = furthest)."""

    layer_starts: array[int]
    layer_ends: array[int]
    kinds: array[int]
    params: array[float]
    colors: array[int]

    @property
    def sprite_count(self) -> int:
        return len(self.kinds)


def try_flatten(layers: Sequence[Shape]) -> FlatScene | None:
    """Return a flat scene when every layer uses supported primitives."""
    packed_layers: list[list[tuple[int, float, float, float, float, RGBA]]] = []
    for layer in layers:
        sprites = _flatten_layer(layer)
        if sprites is None:
            return None
        packed_layers.append(sprites)
    return _pack(packed_layers)


def _pack(
    packed_layers: list[list[tuple[int, float, float, float, float, RGBA]]],
) -> FlatScene:
    layer_starts = array("i")
    layer_ends = array("i")
    kinds = array("B")
    params = array("d")
    colors = array("B")

    for layer in packed_layers:
        layer_starts.append(len(kinds))
        for kind, tx, ty, p0, p1, rgba in layer:
            kinds.append(kind)
            params.extend([tx, ty, p0, p1])
            colors.extend(rgba)
        layer_ends.append(len(kinds))

    return FlatScene(
        layer_starts=layer_starts,
        layer_ends=layer_ends,
        kinds=kinds,
        params=params,
        colors=colors,
    )


def _flatten_layer(shape: Shape) -> list[tuple[int, float, float, float, float, RGBA]] | None:
    return _flatten_shape(shape, 0.0, 0.0)


def _flatten_shape(
    shape: Shape,
    tx: float,
    ty: float,
) -> list[tuple[int, float, float, float, float, RGBA]] | None:
    if isinstance(shape, Translate):
        return _flatten_shape(shape.child, tx + shape.tx, ty + shape.ty)
    if isinstance(shape, Color):
        return _flatten_colored(shape.child, shape.color, tx, ty)
    if isinstance(shape, Union):
        out: list[tuple[int, float, float, float, float, RGBA]] = []
        for member in shape.members:
            part = _flatten_shape(member, tx, ty)
            if part is None:
                return None
            out.extend(part)
        return out
    return None


def _flatten_colored(
    shape: Shape,
    rgba: RGBA,
    tx: float,
    ty: float,
) -> list[tuple[int, float, float, float, float, RGBA]] | None:
    if isinstance(shape, Translate):
        return _flatten_colored(shape.child, rgba, tx + shape.tx, ty + shape.ty)
    if isinstance(shape, Infinite):
        return [(KIND_INFINITE, tx, ty, 0.0, 0.0, rgba)]
    if isinstance(shape, Circle):
        return [(KIND_CIRCLE, tx, ty, shape.radius, 0.0, rgba)]
    if isinstance(shape, Rectangle):
        return [(KIND_RECT, tx, ty, shape.half_width, shape.half_height, rgba)]
    if isinstance(shape, Subtract):
        if isinstance(shape.left, Circle) and isinstance(shape.right, Circle):
            return [
                (
                    KIND_RING,
                    tx,
                    ty,
                    shape.left.radius,
                    shape.right.radius,
                    rgba,
                )
            ]
    return None
