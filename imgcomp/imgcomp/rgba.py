"""Straight RGBA helpers (non-premultiplied)."""

from __future__ import annotations

from typing import Tuple

from imgcomp.native_math import src_over_channels

RGBA = Tuple[int, int, int, int]

TRANSPARENT: RGBA = (0, 0, 0, 0)
WHITE: RGBA = (255, 255, 255, 255)


def clamp_channel(value: float) -> int:
    """Clamp a color channel to [0, 255]."""
    if value <= 0.0:
        return 0
    if value >= 255.0:
        return 255
    return int(round(value))


def modulate(color: RGBA, r_mul: float, g_mul: float, b_mul: float, a_mul: float) -> RGBA:
    """Multiply straight RGBA channels."""
    red, green, blue, alpha = color
    return (
        clamp_channel(red * r_mul),
        clamp_channel(green * g_mul),
        clamp_channel(blue * b_mul),
        clamp_channel(alpha * a_mul),
    )


def src_over(dst: RGBA, src: RGBA) -> RGBA:
    """Composite src over dst using straight alpha."""
    native = src_over_channels(dst[0], dst[1], dst[2], dst[3], src[0], src[1], src[2], src[3])
    if native is not None:
        return native  # type: ignore[return-value]
    sr, sg, sb, sa = src
    dr, dg, db, da = dst
    if sa <= 0:
        return dst
    if sa >= 255:
        return src
    src_a = sa / 255.0
    dst_a = da / 255.0
    out_a = src_a + dst_a * (1.0 - src_a)
    if out_a <= 0.0:
        return TRANSPARENT
    out_r = (sr * src_a + dr * dst_a * (1.0 - src_a)) / out_a
    out_g = (sg * src_a + dg * dst_a * (1.0 - src_a)) / out_a
    out_b = (sb * src_a + db * dst_a * (1.0 - src_a)) / out_a
    return (
        clamp_channel(out_r),
        clamp_channel(out_g),
        clamp_channel(out_b),
        clamp_channel(out_a * 255.0),
    )
