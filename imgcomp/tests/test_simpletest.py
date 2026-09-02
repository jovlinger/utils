# fmt: off
"""simpletest: python circle render, timing, and PNG export."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from imgcomp.rgba import TRANSPARENT, WHITE
from tests.bench_render import BENCH_PATH_KEY, run_selected
from tests.simpletest import VIEWPORT, surface_white_count


def test_simpletest_render_timing_and_png(tmp_path: Path) -> None:
    results = run_selected(["simpletest"], output_dir=tmp_path, repeat=1, warmup=0)
    result = results["simpletest"]
    center = (VIEWPORT // 2 - 1, VIEWPORT // 2 - 1)
    corner = (0, 0)

    bench_path = result.paths[BENCH_PATH_KEY]
    assert bench_path.surface.get_pixel(*center) == WHITE
    assert bench_path.surface.get_pixel(*corner) == TRANSPARENT

    assert surface_white_count(bench_path.surface) == result.extra["white_px"][BENCH_PATH_KEY]
    assert result.extra.get("white_px_ok", True)

    assert result.png_path is not None
    image = Image.open(result.png_path)
    assert image.size == (VIEWPORT, VIEWPORT)
    assert image.getpixel(center) == (255, 255, 255, 255)
    assert image.getpixel(corner) == (0, 0, 0, 0)

    assert bench_path.seconds > 0.0
