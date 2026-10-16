"""The knob glass is round. Layout that misses the circle is a formatting bug."""

from __future__ import annotations

from pathlib import Path

from screenmock.canvas import BLACK, YELLOW

from screenmock.__main__ import write_screenshot
from screenmock.layout import (
    Status,
    ink_outside,
    render_legacy_round,
    render_legacy_square,
    render_round,
    render_square,
    volumio_placeholder,
)


def test_screenshot_uses_volumio_placeholders(tmp_path: Path) -> None:
    shown = volumio_placeholder()
    assert shown.status == "play"
    assert shown.artist == "Sample Artist"
    assert shown.title == "Sample Title"
    assert shown.volume == 42
    path = write_screenshot(tmp_path / "screenshot.png", shown)
    assert path.is_file()
    assert ink_outside(render_square(shown)) == 0


def test_fitted_text_stays_inside_the_circle() -> None:
    image = render_square(Status(title="A Very Long Track Title That Runs Off A Square Screen"))
    assert ink_outside(image) == 0


def test_legacy_bar_and_margin_leave_the_circle() -> None:
    image = render_legacy_square()
    assert ink_outside(image) > 0
    assert image.getpixel((0, 0)) == YELLOW


def test_round_preview_keeps_the_glass_and_dims_the_corner() -> None:
    square = render_square()
    preview = render_round()
    assert preview.getpixel((180, 180)) == square.getpixel((180, 180))
    assert preview.getpixel((0, 0)) != square.getpixel((0, 0))
    assert preview.getpixel((0, 0)) != BLACK


def test_legacy_round_still_shows_the_clipped_bar() -> None:
    preview = render_legacy_round()
    assert preview.getpixel((0, 0)) != YELLOW
    assert preview.getpixel((0, 0)) != BLACK
