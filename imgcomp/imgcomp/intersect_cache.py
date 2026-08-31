"""Per-render cache for ``Shape.intersected_by`` during quadtree culling."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Generator, Optional

from imgcomp.shape import AABB, Shape

_IntersectStore = dict[
    tuple[tuple[Any, ...], tuple[float, float, float, float]], Optional[Shape]
]
_active: ContextVar[_IntersectStore | None] = ContextVar("intersect_cache", default=None)


def cached_intersected_by(shape: Shape, rect: AABB) -> Optional[Shape]:
    """Call ``shape.intersected_by(rect)``, deduplicating within an active session."""
    store = _active.get()
    if store is None:
        return shape.intersected_by(rect)
    key = (shape.cachekey(), rect.as_tuple())
    if key in store:
        return store[key]
    result = shape.intersected_by(rect)
    store[key] = result
    return result


@contextmanager
def intersect_cache_session() -> Generator[None, None, None]:
    """Activate ``cached_intersected_by`` memoization for one quadtree build."""
    token: Token = _active.set({})
    try:
        yield
    finally:
        _active.reset(token)
