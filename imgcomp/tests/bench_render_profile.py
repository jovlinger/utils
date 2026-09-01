#!/usr/bin/env venv-run
"""Profile render phases for rings/spirograph (apples-to-apples breakdown)."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from imgcomp.naive import render_quadtree_python
from imgcomp.stacklang_render import build_quadtree, prepare_scene, viewport_aabb, _iter_leaf_zlists
from tests.fractal_scenes import fractal_gallery_scene

GALLERY_SIZE = 192
SCENES = ("rings", "spirograph")


def _quad_stats(scene, width: int, height: int, *, min_size: float) -> tuple[int, int]:
    layers = prepare_scene(scene)
    tree = build_quadtree(layers, viewport_aabb(width, height), min_size=min_size)
    leaves = _iter_leaf_zlists(tree)

    def count_nodes(node) -> int:
        if node.children is None:
            return 1
        return 1 + sum(count_nodes(c) for c in node.children)

    return count_nodes(tree), len(leaves)


def main() -> int:
    from imgcomp.stacklang_render import render as render_stacklang

    for kind in SCENES:
        scene = fractal_gallery_scene(kind, size=GALLERY_SIZE, profile="fast")
        nodes4, leaves4 = _quad_stats(scene, GALLERY_SIZE, GALLERY_SIZE, min_size=4.0)
        nodes16, leaves16 = _quad_stats(scene, GALLERY_SIZE, GALLERY_SIZE, min_size=16.0)
        print(f"{kind} ({GALLERY_SIZE}x{GALLERY_SIZE}):")
        print(f"  quadtree min_size=4:  nodes={nodes4} leaves={leaves4}")
        print(f"  quadtree min_size=16: nodes={nodes16} leaves={leaves16}")
        render_quadtree_python(scene, GALLERY_SIZE, GALLERY_SIZE, min_size=16.0)
        print("  python: ok")
        render_stacklang(scene, GALLERY_SIZE, GALLERY_SIZE)
        print("  imgcomp_stacklang: ok")
        render_stacklang(scene, GALLERY_SIZE, GALLERY_SIZE)
        print("  imgcomp_stacklang_warm2: ok")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
