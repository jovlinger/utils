#!/usr/bin/env python3
"""Pytest hooks and fast tile-cache stubs for vox2stl tests."""

from __future__ import annotations

from typing import Dict, List, Tuple

import pytest

import vox2stl
from constants import DEFAULT_LABEL_HEIGHT_FRAC, DEFAULT_LABEL_RECESS_FRAC

Tri = vox2stl.Tri
TileCacheKey = vox2stl.TileCacheKey

_MOCK_TILE_CACHE: Dict[TileCacheKey, List[Tri]] = {}
_LETTER_TEMPLATE_CACHE: Dict[str, List[Tri]] = {}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "real_tile_cache: exercise real persistent tile cache (no autouse mocks)",
    )


def _stub_trace_tris(config: vox2stl.RenderConfig) -> List[Tri]:
    box = vox2stl.square_box(0.0, 0.0, vox2stl.trace_width(config), config.trace_z0_mm, config.trace_z1_mm)
    return vox2stl.mesh_from_boxes([box]).triangles


def _letter_template(letter: str) -> List[Tri]:
    cached = _LETTER_TEMPLATE_CACHE.get(letter)
    if cached is not None:
        return cached
    recess = DEFAULT_LABEL_RECESS_FRAC
    height = DEFAULT_LABEL_HEIGHT_FRAC
    x0 = recess + 0.05
    x1 = 0.55 if letter == "F" else 0.40
    y0 = recess
    y1 = 1.0 - recess
    tris: List[Tri] = []
    for index in range(120):
        offset = index * 0.0004
        top_z = height
        quad = (
            (x0 + offset, y0 + offset, top_z),
            (x1 - offset, y0 + offset, top_z),
            (x1 - offset, y1 - offset, top_z),
        )
        tris.append((quad[0], quad[1], quad[2]))
        tris.append((quad[0], quad[2], (x0 + offset, y1 - offset, top_z)))
        wall_z0 = 0.0
        tris.append(((x0, y0, wall_z0), (x1, y0, wall_z0), (x1, y0, top_z)))
    _LETTER_TEMPLATE_CACHE[letter] = tris
    return tris


def _mock_load_letter_tile(letter: str) -> List[Tri]:
    return _letter_template(letter.upper())


def _mock_cached_tile_tris(
    key: TileCacheKey,
    config: vox2stl.RenderConfig,
    real_cached_tile_tris,
) -> List[Tri]:
    cached = _MOCK_TILE_CACHE.get(key)
    if cached is not None:
        return cached
    if isinstance(key, str):
        if vox2stl.is_label_char(key):
            tris = vox2stl.place_letter_tris(_mock_load_letter_tile(key), 0.0, 0.0, config)
        elif key in vox2stl.PAD_CHARS:
            tris = real_cached_tile_tris(key, config)
        elif key in vox2stl.ARMS_BY_CHAR:
            tris = _stub_trace_tris(config)
        else:
            tris = []
    else:
        char = key[0]
        if char in vox2stl.PAD_CHARS:
            tris = real_cached_tile_tris(key, config)
        else:
            tris = _stub_trace_tris(config)
    _MOCK_TILE_CACHE[key] = tris
    return tris


def _mock_cached_negative_base_letter_tris(
    char: str,
    config: vox2stl.RenderConfig,
    real_cached_negative_base_letter_tris,
) -> List[Tri]:
    key = vox2stl.negative_base_letter_cache_key(char)
    cached = _MOCK_TILE_CACHE.get(key)
    if cached is not None:
        return cached
    tris = real_cached_negative_base_letter_tris(char, config)
    _MOCK_TILE_CACHE[key] = tris
    return tris


@pytest.fixture(autouse=True)
def mock_tile_cache_access(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if request.node.get_closest_marker("real_tile_cache") is not None:
        yield
        return

    _MOCK_TILE_CACHE.clear()
    real_cached_tile_tris = vox2stl.cached_tile_tris
    real_cached_negative_base_letter_tris = vox2stl.cached_negative_base_letter_tris

    monkeypatch.setattr(vox2stl, "persistent_tile_cache_enabled", lambda config: False)
    monkeypatch.setattr(vox2stl, "seed_pre_rendered_letters", lambda cache, config: None)
    monkeypatch.setattr(vox2stl, "load_letter_tile", _mock_load_letter_tile)
    monkeypatch.setattr(
        vox2stl,
        "cached_tile_tris",
        lambda key, config: _mock_cached_tile_tris(key, config, real_cached_tile_tris),
    )
    monkeypatch.setattr(
        vox2stl,
        "cached_negative_base_letter_tris",
        lambda char, config: _mock_cached_negative_base_letter_tris(
            char,
            config,
            real_cached_negative_base_letter_tris,
        ),
    )
    yield
    _MOCK_TILE_CACHE.clear()
