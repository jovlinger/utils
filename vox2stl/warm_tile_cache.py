#!/usr/bin/env python3
"""Rebuild the persistent vox2stl tile cache for the default geometry profile."""

from __future__ import annotations

import gzip
import pickle
import sys
from pathlib import Path
from typing import Sequence

import vox2stl
from constants import TILE_CACHE_PATH
from vox2stl import TILE_CACHE_SIGNATURE_KEY, flush_persistent_tile_cache, tile_cache_signature

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
VOX_SOURCES: Sequence[Path] = (
    ROOT / "testdata" / "straight.vox",
    ROOT / "testdata" / "box_glyphs.vox",
    REPO_ROOT / "thermo" / "onboard" / "hardware" / "pico2w" / "hat" / "up-side.vox",
)


def verify_tile_cache(path: Path) -> int:
    with gzip.open(path, "rb") as file_obj:
        cache = pickle.load(file_obj)
    if not isinstance(cache, dict):
        raise ValueError(f"{path}: tile cache is not a dictionary")
    if TILE_CACHE_SIGNATURE_KEY not in cache:
        raise ValueError(f"{path}: tile cache is missing signature key")
    return len(cache)


def warm_vox(path: Path) -> None:
    print(f"warming from {path}...", flush=True)
    layers = vox2stl.read_layers(path)
    unit = vox2stl.unit_from_file(path) or vox2stl.DEFAULT_UNIT_MM
    config = vox2stl.RenderConfig(unit_mm=unit)
    base_layer = layers.get("base")
    trace_layer = layers.get("trace")
    if base_layer is not None and trace_layer is not None:
        vox2stl.full_mesh_from_layers(base_layer, trace_layer, config)
        return
    if trace_layer is not None:
        vox2stl.build_layer_mesh(trace_layer, config)
        return
    raise ValueError(f"{path}: missing trace layer")


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    missing = [path for path in VOX_SOURCES if not path.is_file()]
    if missing:
        for path in missing:
            print(f"error: missing warmup source {path}", file=sys.stderr)
        return 1

    if TILE_CACHE_PATH.is_file():
        TILE_CACHE_PATH.unlink()
    vox2stl._PERSISTENT_TILE_CACHE = None
    vox2stl._PERSISTENT_TILE_CACHE_DIRTY = False

    for path in VOX_SOURCES:
        warm_vox(path)

    flush_persistent_tile_cache()
    key_count = verify_tile_cache(TILE_CACHE_PATH)
    signature = tile_cache_signature(vox2stl.RenderConfig())
    print(f"ok wrote {TILE_CACHE_PATH} ({key_count} keys, signature={signature})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
