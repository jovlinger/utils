"""Normalize a scene root to a z-ordered shape list (back to front)."""

from __future__ import annotations

from collections.abc import Sequence

from imgcomp.shape import Shape

Scene = Shape | Sequence[Shape]


def as_z_list(root: Scene) -> tuple[Shape, ...]:
    """Return scene layers ordered furthest (index 0) to closest (index -1)."""
    if isinstance(root, Shape):
        return (root,)
    if isinstance(root, (str, bytes)):
        raise TypeError("scene root must be a Shape or a sequence of Shape")
    return tuple(root)


def as_scene(root: Scene) -> tuple[Shape, ...]:
    """Alias for as_z_list kept for compositor entry points."""
    return as_z_list(root)
