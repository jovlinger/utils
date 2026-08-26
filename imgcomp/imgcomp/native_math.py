"""Optional Cython leaf-math helpers (distances, src-over, pixel write)."""

from __future__ import annotations

from typing import Optional

try:
    from imgcomp import _math as _native
except ImportError:  # pragma: no cover - extension not built yet
    _native = None


def native_available() -> bool:
    """Return True when the compiled math extension is importable."""
    return _native is not None


def circle_distance(x: float, y: float, radius: float) -> Optional[float]:
    if _native is None:
        return None
    return float(_native.circle_distance(x, y, radius))


def rectangle_distance(
    x: float,
    y: float,
    half_width: float,
    half_height: float,
) -> Optional[float]:
    if _native is None:
        return None
    return float(_native.rectangle_distance(x, y, half_width, half_height))


def oval_distance(
    x: float,
    y: float,
    radius_x: float,
    radius_y: float,
) -> Optional[float]:
    if _native is None:
        return None
    return float(_native.oval_distance(x, y, radius_x, radius_y))


def src_over_channels(
    dr: int,
    dg: int,
    db: int,
    da: int,
    sr: int,
    sg: int,
    sb: int,
    sa: int,
) -> Optional[tuple[int, int, int, int]]:
    if _native is None:
        return None
    return _native.src_over(dr, dg, db, da, sr, sg, sb, sa)


def set_pixel_rgba(
    buffer: object,
    offset: int,
    red: int,
    green: int,
    blue: int,
    alpha: int,
) -> bool:
    """Write RGBA via Cython when available; return False to use Python path."""
    if _native is None:
        return False
    _native.set_pixel_rgba(buffer, offset, red, green, blue, alpha)
    return True
