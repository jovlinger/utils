#!/usr/bin/env venv-run
"""Profile render phases for rings/spirograph (apples-to-apples breakdown)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from imgcomp.naive import render_quadtree_python
from imgcomp.render_profile import RenderProfile
from imgcomp.stacklang_render import (
    build_quadtree,
    prepare_scene,
    viewport_aabb,
    _iter_leaf_zlists,
)
from tests.fractal_scenes import fractal_gallery_scene

GALLERY_SIZE = 192
SCENES = ("rings", "spirograph")
MIN_SIZE = 16.0


def _print_profile(branch: str, path_key: str, profile: RenderProfile) -> None:
    parts = [f"{name}={ms:.3f}ms" for name, ms in profile.as_dict_ms().items()]
    print(
        f"  branch={branch} path={path_key} total={profile.total_ms():.3f}ms  "
        + "  ".join(parts)
    )


def _quad_stats(scene, width: int, height: int, *, min_size: float) -> tuple[int, int]:
    layers = prepare_scene(scene)
    tree = build_quadtree(layers, viewport_aabb(width, height), min_size=min_size)
    leaves = _iter_leaf_zlists(tree)

    def count_nodes(node) -> int:
        if node.children is None:
            return 1
        return 1 + sum(count_nodes(c) for c in node.children)

    return count_nodes(tree), len(leaves)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--branch",
        required=True,
        help="git branch name for labels (e.g. master)",
    )
    args = parser.parse_args(argv)
    branch = args.branch

    print(f"=== branch {branch} ===")
    for kind in SCENES:
        scene = fractal_gallery_scene(kind, size=GALLERY_SIZE, profile="fast")
        nodes4, leaves4 = _quad_stats(scene, GALLERY_SIZE, GALLERY_SIZE, min_size=4.0)
        nodes16, leaves16 = _quad_stats(scene, GALLERY_SIZE, GALLERY_SIZE, min_size=MIN_SIZE)
        print(f"{kind} ({GALLERY_SIZE}x{GALLERY_SIZE}):")
        print(f"  quadtree min_size=4:  nodes={nodes4} leaves={leaves4}")
        print(f"  quadtree min_size={MIN_SIZE}: nodes={nodes16} leaves={leaves16}")

        py_profile = RenderProfile()
        render_quadtree_python(
            scene, GALLERY_SIZE, GALLERY_SIZE, min_size=MIN_SIZE, profile=py_profile
        )
        _print_profile(branch, "python", py_profile)

        render_quadtree_python(scene, GALLERY_SIZE, GALLERY_SIZE, min_size=MIN_SIZE)
        py_warm = RenderProfile()
        render_quadtree_python(
            scene, GALLERY_SIZE, GALLERY_SIZE, min_size=MIN_SIZE, profile=py_warm
        )
        _print_profile(branch, "python_warm2", py_warm)

        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
