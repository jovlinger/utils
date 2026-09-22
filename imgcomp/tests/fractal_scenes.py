"""Fractal and decorative scene builders for gallery and perf tests."""

from __future__ import annotations

import math

from imgcomp.rgba import RGBA
from imgcomp.shape import Shape
from imgcomp.shapes import Circle, Infinite, Rectangle

GALLERY_BACKGROUND: RGBA = (12, 14, 24, 255)


def _hsv_disk_color(index: int, total: int, saturation: float = 0.75, value: float = 0.95) -> RGBA:
    hue = (index / max(total, 1)) % 1.0
    chroma = value * saturation
    segment = hue * 6.0
    sector = int(segment) % 6
    minimum = value - chroma
    mid = minimum + chroma * max(0.0, min(1.0, 2.0 - abs(segment - 2.0)))
    if sector == 0:
        red, green, blue = value, mid, minimum
    elif sector == 1:
        red, green, blue = mid, value, minimum
    elif sector == 2:
        red, green, blue = minimum, value, mid
    elif sector == 3:
        red, green, blue = minimum, mid, value
    elif sector == 4:
        red, green, blue = mid, minimum, value
    else:
        red, green, blue = value, minimum, mid
    return (int(round(red * 255.0)), int(round(green * 255.0)), int(round(blue * 255.0)), 230)


def sierpinski_carpet(level: int, half_size: float, fill: RGBA) -> Shape:
    """Square Sierpinski carpet built from nested square unions."""
    if level <= 0:
        return Rectangle(half_size, half_size).color(fill)
    sub_half = half_size / 3.0
    step = (2.0 * half_size) / 3.0
    parts: list[Shape] = []
    for row in (-1, 0, 1):
        for col in (-1, 0, 1):
            if row == 0 and col == 0:
                continue
            parts.append(
                sierpinski_carpet(level - 1, sub_half, fill).translate(col * step, row * step)
            )
    return parts[0].union(*parts[1:])


def phyllotaxis_spiral(dot_count: int, dot_radius: float, spread: float) -> Shape:
    """Sunflower / Vogel spiral of small disks."""
    golden_angle = math.pi * (3.0 - math.sqrt(5.0))
    dots: list[Shape] = []
    for index in range(dot_count):
        radius = spread * math.sqrt(float(index))
        angle = index * golden_angle
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        dots.append(
            Circle(dot_radius)
            .translate(x, y)
            .color(_hsv_disk_color(index, dot_count))
        )
    return dots[0].union(*dots[1:])


def concentric_ring_fractal(ring_count: int, outer_radius: float) -> Shape:
    """Nested annuli with a warm-to-cool palette."""
    rings: list[Shape] = []
    for index in range(ring_count):
        outer = outer_radius * float(ring_count - index) / float(ring_count)
        inner = outer_radius * float(ring_count - index - 1) / float(ring_count) * 0.92
        if inner <= 1.0:
            geometry = Circle(outer)
        else:
            geometry = Circle(outer).subtract(Circle(inner))
        rings.append(geometry.color(_hsv_disk_color(index, ring_count, saturation=0.85, value=1.0)))
    return rings[0].union(*rings[1:])


def spirograph_rosette(petal_count: int, major_radius: float, minor_radius: float) -> Shape:
    """Dots tracing a hypotrochoid-like rosette."""
    dots: list[Shape] = []
    steps = max(petal_count * 12, 24)
    ratio = major_radius / max(minor_radius, 1e-6)
    for step in range(steps):
        t = (2.0 * math.pi * step) / steps
        x = (major_radius - minor_radius) * math.cos(t) + minor_radius * math.cos(ratio * t)
        y = (major_radius - minor_radius) * math.sin(t) - minor_radius * math.sin(ratio * t)
        dots.append(
            Circle(minor_radius * 0.18)
            .translate(x, y)
            .color(_hsv_disk_color(step, steps, saturation=0.9, value=1.0))
        )
    return dots[0].union(*dots[1:])


def fractal_gallery_scene(kind: str, *, size: int, profile: str = "fast") -> list[Shape]:
    """Return a z-ordered scene for a named fractal preset."""
    bg = Infinite().color(GALLERY_BACKGROUND)
    half = float(size) * 0.38
    if profile == "fast":
        presets = {
            "carpet": lambda: sierpinski_carpet(2, half, (235, 210, 145, 255)),
            "phyllotaxis": lambda: phyllotaxis_spiral(36, max(1.4, size / 120.0), half * 0.9),
            "rings": lambda: concentric_ring_fractal(8, half * 0.95),
            "spirograph": lambda: spirograph_rosette(5, half * 0.85, half * 0.22),
        }
    elif profile == "slow":
        presets = {
            "carpet": lambda: sierpinski_carpet(3, half, (235, 210, 145, 255)),
            "phyllotaxis": lambda: phyllotaxis_spiral(36, max(1.4, size / 140.0), half * 0.9),
            "rings": lambda: concentric_ring_fractal(10, half * 0.95),
            "spirograph": lambda: spirograph_rosette(6, half * 0.85, half * 0.22),
        }
    else:
        raise ValueError(f"unknown profile: {profile}")
    if kind not in presets:
        raise ValueError(f"unknown fractal kind: {kind}")
    return [bg, presets[kind]()]
