"""Tests for straight-alpha helpers."""

from __future__ import annotations

from imgcomp.rgba import src_over


def test_src_over_opaque_source_replaces_destination() -> None:
    assert src_over((10, 20, 30, 255), (200, 100, 50, 255)) == (200, 100, 50, 255)


def test_src_over_transparent_source_keeps_destination() -> None:
    assert src_over((10, 20, 30, 255), (0, 0, 0, 0)) == (10, 20, 30, 255)
