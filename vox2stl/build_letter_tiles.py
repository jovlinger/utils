#!/usr/bin/env python3
"""Pre-render A-Z letter tiles as high-resolution binary STL."""

from __future__ import annotations

import sys
from pathlib import Path

import vox2stl


def main() -> int:
    out_dir = vox2stl.LETTER_TILES_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_lines = [
        "# vox2stl letter tile manifest",
        "source=hershey_simplex_smoothed",
        f"recess_frac={vox2stl.DEFAULT_LABEL_RECESS_FRAC}",
        f"height_frac={vox2stl.DEFAULT_LABEL_HEIGHT_FRAC}",
        "letter triangles",
    ]
    total_triangles = 0
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        tris = vox2stl.generate_letter_tile_triangles(letter)
        path = out_dir / f"{letter}.stl"
        vox2stl.write_binary_stl(path, tris, f"letter_{letter}")
        manifest_lines.append(f"{letter} {len(tris)}")
        total_triangles += len(tris)
        print(f"wrote {path.name}: {len(tris)} triangles")
    manifest_lines.append(f"total {total_triangles}")
    (out_dir / "manifest.txt").write_text("\n".join(manifest_lines) + "\n", encoding="ascii")
    print(f"ok letter tiles in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
