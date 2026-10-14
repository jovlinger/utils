"""Status layout for the round knob glass.

The fitted layout matches firmware draw_status. The legacy layout is the
previous square-screen placement, kept so the circular clip stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from screenmock.canvas import (
    BLACK,
    GLYPH_H,
    GLYPH_W,
    HEIGHT,
    WHITE,
    WIDTH,
    YELLOW,
    Canvas,
    box_inside_circle,
    round_preview,
)

TEXT_SIZE = 2
LINE_H = GLYPH_H * TEXT_SIZE


@dataclass(frozen=True)
class Status:
    awake: bool = True
    status: str = "pause"
    artist: str = ""
    title: str = "miniDSP-SHD.local"
    volume: int = 59
    activity: str = ""


def _lines(status: Status) -> list[tuple[str, tuple[int, int, int]]]:
    return [
        ("spinme" if status.awake else "asleep", YELLOW),
        (status.status, WHITE),
        (status.artist, WHITE),
        (status.title, WHITE),
        ("vol {0}".format(status.volume), WHITE),
        (status.activity, WHITE),
    ]


def fit_line(text: str, y: int, size: int = TEXT_SIZE) -> str:
    """Drop trailing characters until the centered cell sits in the circle."""
    fitted = text
    cell_w = GLYPH_W * size
    cell_h = GLYPH_H * size
    while fitted:
        width = len(fitted) * cell_w
        x = (WIDTH - width) // 2
        if box_inside_circle(x, y, width, cell_h):
            return fitted
        fitted = fitted[:-1]
    return ""


def render_square(status: Status | None = None) -> Image.Image:
    shown = status if status is not None else Status()
    canvas = Canvas()
    canvas.fill(BLACK)
    visible = [(text, color) for text, color in _lines(shown) if text]
    origin = (HEIGHT - len(visible) * LINE_H) // 2
    for index, (text, color) in enumerate(visible):
        line_y = origin + index * LINE_H
        fitted = fit_line(text, line_y)
        if not fitted:
            continue
        width = len(fitted) * GLYPH_W * TEXT_SIZE
        x = (WIDTH - width) // 2
        canvas.text(fitted, x, line_y, TEXT_SIZE, color)
    return canvas.image


def render_round(status: Status | None = None) -> Image.Image:
    return round_preview(render_square(status))


def render_legacy_square(status: Status | None = None) -> Image.Image:
    """Left-aligned block and a full-width bar. Corners fall off the round glass."""
    shown = status if status is not None else Status()
    canvas = Canvas()
    canvas.fill(BLACK)
    canvas.fill_rect(0, 0, WIDTH, 28, YELLOW)
    canvas.text("spinme" if shown.awake else "asleep", 16, 6, TEXT_SIZE, BLACK)
    canvas.text(shown.status, 16, 48, TEXT_SIZE, WHITE)
    canvas.text(shown.artist, 16, 96, TEXT_SIZE, WHITE)
    canvas.text(shown.title, 16, 144, TEXT_SIZE, WHITE)
    canvas.text("vol {0}".format(shown.volume), 16, 200, TEXT_SIZE, WHITE)
    canvas.text(shown.activity, 16, 260, TEXT_SIZE, WHITE)
    return canvas.image


def render_legacy_round(status: Status | None = None) -> Image.Image:
    return round_preview(render_legacy_square(status))


def ink_outside(image: Image.Image, background: tuple[int, int, int] = BLACK) -> int:
    canvas = Canvas()
    canvas.image = image
    canvas._px = image.load()
    return canvas.ink_outside_circle(background)
