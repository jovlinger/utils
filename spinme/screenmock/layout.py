"""Status layout for the round knob glass.

The fitted layout matches firmware draw_status. A line is l2r of glyph
boxes and zero-area shims (letter between letters, word between words),
bottom-aligned. Lines stack with t2b, left-aligned, with a line shim
inside a section and a section shim between sections. The union center
sits on the glass center. The legacy layout is the previous
square-screen placement, kept so the circular clip stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from screenmock.canvas import (
    BLACK,
    HEIGHT,
    WHITE,
    WIDTH,
    YELLOW,
    Canvas,
    box_inside_circle,
    round_preview,
    text_width,
)
from screenmock.compose import Box, HAlign, Placed, UnionBox, t2b
from screenmock.glyphfile import line_box, line_vshim, mapped, section_vshim

TEXT_SIZE = 1
TRANSPORT_Y = 24
TRANSPORT_PAD_X = 12
TRANSPORT_PAD_Y = 6


@dataclass(frozen=True)
class Status:
    awake: bool = True
    status: str = "pause"
    artist: str = ""
    title: str = "miniDSP-SHD.local"
    volume: int = 59
    activity: str = ""


def volumio_placeholder() -> Status:
    """Stand-in for Volumio getState. The host screenshot does not call the player."""
    return Status(
        awake=True,
        status="play",
        artist="Sample Artist",
        title="Sample Title",
        volume=42,
        activity="",
    )


def transport_label(status: str) -> str:
    if status == "play":
        return "stop"
    return "play"


def _lines(status: Status) -> list[tuple[str, tuple[int, int, int], int]]:
    """Text, color, section. Sections are separated by the section vshim."""
    return [
        ("spinme" if status.awake else "asleep", YELLOW, 0),
        (status.status, WHITE, 0),
        (status.artist, WHITE, 1),
        (status.title, WHITE, 1),
        ("vol {0}".format(status.volume), WHITE, 2),
        (status.activity, WHITE, 2),
    ]


def _draw_transport(canvas: Canvas, status: Status) -> None:
    label = transport_label(status.status)
    text_w = max(text_width("play"), text_width("stop"))
    text_h = mapped().height
    width = text_w + TRANSPORT_PAD_X * 2
    height = text_h + TRANSPORT_PAD_Y * 2
    x = (WIDTH - width) // 2
    canvas.fill_rect(x, TRANSPORT_Y, width, height, WHITE)
    label_w = text_width(label)
    label_x = x + TRANSPORT_PAD_X + (text_w - label_w) // 2
    canvas.text(label, label_x, TRANSPORT_Y + TRANSPORT_PAD_Y, TEXT_SIZE, BLACK)


def _block(
    texts: list[str], sections: list[int]
) -> tuple[UnionBox, list[str], list[Placed]]:
    boxes: list[Box] = []
    live: list[str] = []
    prev_section: int | None = None
    for text, section in zip(texts, sections):
        sized = line_box(text)
        if sized is None:
            continue
        if boxes:
            if section != prev_section:
                boxes.append(section_vshim())
            else:
                boxes.append(line_vshim())
        boxes.append(sized)
        live.append(text)
        prev_section = section
    union = t2b(boxes, HAlign.left)
    lines = [child for child in union.children if child.w > 0 and child.h > 0]
    return union, live, lines


def _screen_rect(child: Placed) -> tuple[int, int, int, int]:
    left = WIDTH // 2 + child.left()
    top = HEIGHT // 2 + child.top()
    return (left, top, child.w, child.h)


def fit_block(texts: list[str], sections: list[int] | None = None) -> list[str]:
    """Drop trailing characters until every left-aligned line is in the circle."""
    fitted = list(texts)
    groups = list(sections) if sections is not None else [0] * len(fitted)
    while True:
        _union, live, lines = _block(fitted, groups)
        if not live:
            return fitted
        worst = -1
        worst_w = -1
        produced = [i for i, text in enumerate(fitted) if line_box(text) is not None]
        for src, child in zip(produced, lines):
            left, top, width, height = _screen_rect(child)
            if not box_inside_circle(left, top, width, height) and width > worst_w:
                worst = src
                worst_w = width
        if worst < 0:
            return fitted
        fitted[worst] = fitted[worst][:-1]


def fitted_line_boxes(
    texts: list[str], sections: list[int] | None = None
) -> list[tuple[int, int, int, int]]:
    """Screen rects of the glyph lines. Shims are in the union, not returned."""
    groups = list(sections) if sections is not None else [0] * len(texts)
    _union, _live, lines = _block(fit_block(texts, groups), groups)
    return [_screen_rect(child) for child in lines]


def render_square(status: Status | None = None) -> Image.Image:
    shown = status if status is not None else Status()
    canvas = Canvas()
    canvas.fill(BLACK)
    visible = [(text, color, section) for text, color, section in _lines(shown) if text]
    groups = [section for _text, _color, section in visible]
    fitted = fit_block([text for text, _color, _section in visible], groups)
    paired = [
        (text, color)
        for text, (_raw, color, _section) in zip(fitted, visible)
        if line_box(text) is not None
    ]
    _union, _live, lines = _block(fitted, groups)
    for child, (text, color) in zip(lines, paired):
        left, top, _width, _height = _screen_rect(child)
        canvas.text(text, left, top, TEXT_SIZE, color)
    _draw_transport(canvas, shown)
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
