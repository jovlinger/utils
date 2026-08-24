"""Tests for Circle and ImageObject."""

from __future__ import annotations

from imgcomp.primitives import Circle, ImageObject


def test_circle_hit_uses_radius_from_center() -> None:
    circle = Circle(3.0, (255, 255, 255, 255))
    assert circle.hit(2.9, 0.0) is True
    assert circle.hit(3.1, 0.0) is False


def test_image_hit_uses_full_aabb_including_transparent_texels() -> None:
    image = ImageObject.from_rgba_rows(
        [
            [(255, 0, 0, 255), (0, 0, 0, 0)],
            [(0, 0, 0, 0), (0, 0, 255, 255)],
        ]
    )
    assert image.hit(0.0, 0.0) is True
    assert image.hit(0.6, -0.4) is True
    assert image.hit(1.1, 0.0) is False


def test_image_sample_reads_center_based_texel() -> None:
    image = ImageObject.from_rgba_rows([[(10, 20, 30, 40)]])
    assert image.sample(0.0, 0.0) == (10, 20, 30, 40)
