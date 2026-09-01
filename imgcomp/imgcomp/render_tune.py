"""Adaptive quadtree min_size tuning via hillclimb on RMS frame time."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from imgcomp.scene import Scene
    from imgcomp.surface import Surface

RenderFn = Callable[..., "Surface"]

_TUNED: dict[str, float] = {}


def tuned_min_size(path_key: str, default: float = 16.0) -> float:
    """Return hillclimbed min_size for a render path key, or default."""
    return _TUNED.get(path_key, default)


def hillclimb_min_size(
    path_key: str,
    render_fn: RenderFn,
    scene: "Scene",
    width: int,
    height: int,
    *,
    candidates: Sequence[float] = (4.0, 8.0, 16.0, 32.0),
    repeat: int = 2,
    warmup: int = 1,
) -> float:
    """Pick min_size minimizing RMS per-frame milliseconds for one render path."""
    import time

    if repeat < 1:
        raise ValueError("repeat must be >= 1")

    best_size = float(candidates[0])
    best_rms = math.inf

    for min_size in candidates:
        for _ in range(warmup):
            render_fn(scene, width, height, min_size=min_size)
        samples: list[float] = []
        for _ in range(repeat):
            start = time.perf_counter()
            render_fn(scene, width, height, min_size=min_size)
            samples.append((time.perf_counter() - start) * 1000.0)
        rms = math.sqrt(sum(ms * ms for ms in samples) / len(samples))
        if rms < best_rms:
            best_rms = rms
            best_size = float(min_size)

    _TUNED[path_key] = best_size
    return best_size


def clear_tuned() -> None:
    """Reset cached hillclimb results (tests)."""
    _TUNED.clear()
