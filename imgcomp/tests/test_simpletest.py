# fmt: off
"""simpletest: stacklang circle render, timing, and PNG export."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from imgcomp.rgba import TRANSPARENT, WHITE
from tests.bench_render import run_selected
from tests.simpletest import VIEWPORT, surface_white_count


def test_simpletest_render_timing_and_png(tmp_path: Path) -> None:
    results = run_selected(["simpletest"], output_dir=tmp_path, repeat=1, warmup=0)
    result = results["simpletest"]
    center = (VIEWPORT // 2 - 1, VIEWPORT // 2 - 1)
    corner = (0, 0)

    for path in result.paths.values():
        assert path.surface.get_pixel(*center) == WHITE
        assert path.surface.get_pixel(*corner) == TRANSPARENT

    py_surface = result.paths["python"].surface
    assert surface_white_count(py_surface) == surface_white_count(
        result.paths["stacklang"].surface
    )
    assert surface_white_count(py_surface) == surface_white_count(result.paths["c"].surface)

    assert result.png_path is not None
    image = Image.open(result.png_path)
    assert image.size == (VIEWPORT, VIEWPORT)
    assert image.getpixel(center) == (255, 255, 255, 255)
    assert image.getpixel(corner) == (0, 0, 0, 0)

    assert result.paths["python"].seconds > 0.0
    assert result.paths["stacklang"].seconds > 0.0
    assert result.paths["c"].seconds > 0.0
