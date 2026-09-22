"""Tests for Affine composition and invert."""

from __future__ import annotations

import pytest

from imgcomp.affine import Affine


def test_translate_roundtrip() -> None:
    aff = Affine.translate(3.0, -2.0)
    gx, gy = aff.transform(1.0, 4.0)
    assert (gx, gy) == (4.0, 2.0)
    assert aff.to_local(gx, gy) == (1.0, 4.0)


def test_compose_translate_then_stretch() -> None:
    aff = Affine.translate(5.0, 0.0) @ Affine.stretch(2.0, 1.0)
    gx, gy = aff.transform(1.0, 0.0)
    assert (gx, gy) == (7.0, 0.0)


def test_rotate_90_degrees() -> None:
    aff = Affine.rotate(90.0)
    gx, gy = aff.transform(1.0, 0.0)
    assert gx == pytest.approx(0.0, abs=1e-12)
    assert gy == pytest.approx(1.0, abs=1e-12)
