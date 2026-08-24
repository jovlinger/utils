"""Normalize a scene root to a z-ordered object list (back to front)."""

from __future__ import annotations

from collections.abc import Sequence

from imgcomp.object import Object

Scene = Object | Sequence[Object]


def as_z_list(root: Scene) -> tuple[Object, ...]:
    """Return scene layers ordered furthest (index 0) to closest (index -1)."""
    if isinstance(root, Object):
        return (root,)
    if isinstance(root, (str, bytes)):
        raise TypeError("scene root must be an Object or a sequence of Object")
    return tuple(root)


def as_scene(root: Scene) -> tuple[Object, ...]:
    """Alias for as_z_list kept for compositor entry points."""
    return as_z_list(root)
