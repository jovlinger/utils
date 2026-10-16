"""Left-to-right and top-to-bottom box composition.

The result is the tight union of the inputs. Its origin is the center
of that box: child (cx, cy) is the child's center in this frame.
Keep this in step with firmware include/layout_box.h.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class VAlign(Enum):
    top = "top"
    vcenter = "vcenter"
    bot = "bot"


class HAlign(Enum):
    left = "left"
    hcenter = "hcenter"
    right = "right"


@dataclass(frozen=True)
class Box:
    w: int
    h: int


@dataclass(frozen=True)
class Placed:
    """Child center in the parent frame, whose origin is the parent center."""

    cx: int
    cy: int
    w: int
    h: int

    def left(self) -> int:
        return self.cx - self.w // 2

    def top(self) -> int:
        return self.cy - self.h // 2


@dataclass(frozen=True)
class UnionBox:
    """Tight bounding box around the origin at the box center."""

    x: int
    y: int
    w: int
    h: int
    children: tuple[Placed, ...]


def _start(span: int, size: int, mode: int) -> int:
    if mode == 0:
        return 0
    if mode == 1:
        return (span - size) // 2
    return span - size


def hshim(px: int) -> Box:
    """Zero-area horizontal spacer for l2r. Width is px, height is 0."""
    return Box(px, 0)


def vshim(px: int) -> Box:
    """Zero-area vertical spacer for t2b. Width is 0, height is px."""
    return Box(0, px)


def l2r(boxes: list[Box], valign: VAlign) -> UnionBox:
    """Lay boxes left to right. valign is top, vcenter, or bot."""
    mode = {VAlign.top: 0, VAlign.vcenter: 1, VAlign.bot: 2}[valign]
    return _pack(boxes, mode, horizontal=True)


def t2b(boxes: list[Box], halign: HAlign) -> UnionBox:
    """Lay boxes top to bottom. halign is left, hcenter, or right."""
    mode = {HAlign.left: 0, HAlign.hcenter: 1, HAlign.right: 2}[halign]
    return _pack(boxes, mode, horizontal=False)


def _pack(boxes: list[Box], mode: int, horizontal: bool) -> UnionBox:
    if not boxes:
        return UnionBox(0, 0, 0, 0, ())
    main = 0
    cross = 0
    for box in boxes:
        if horizontal:
            main += box.w
            if box.h > cross:
                cross = box.h
        else:
            main += box.h
            if box.w > cross:
                cross = box.w
    origin_main = main // 2
    origin_cross = cross // 2
    placed: list[Placed] = []
    cursor = 0
    for box in boxes:
        if horizontal:
            cross_at = _start(cross, box.h, mode)
            placed.append(
                Placed(
                    cx=cursor + box.w // 2 - origin_main,
                    cy=cross_at + box.h // 2 - origin_cross,
                    w=box.w,
                    h=box.h,
                )
            )
            cursor += box.w
        else:
            cross_at = _start(cross, box.w, mode)
            placed.append(
                Placed(
                    cx=cross_at + box.w // 2 - origin_cross,
                    cy=cursor + box.h // 2 - origin_main,
                    w=box.w,
                    h=box.h,
                )
            )
            cursor += box.h
    if horizontal:
        return UnionBox(-origin_main, -origin_cross, main, cross, tuple(placed))
    return UnionBox(-origin_cross, -origin_main, cross, main, tuple(placed))


@dataclass(frozen=True)
class MarqueeTile:
    """One clipped slice of the background, in viewport top-left coordinates."""

    x: int
    y: int
    w: int
    h: int
    src_x: int
    src_y: int


@dataclass(frozen=True)
class HMarquee:
    """External box is the viewport. Tiles are the background translated and clipped."""

    w: int
    h: int
    tiles: tuple[MarqueeTile, ...]


def hmarquee(viewport: Box, background: Box, t: int) -> HMarquee:
    """Slide a viewport across a background. t is pixels of travel.

    The background repeats end to start, so the join has no extra gap.
    A trailing blank shows up only when that blank is part of the background.
    """
    view_w = viewport.w if viewport.w > 0 else 0
    view_h = viewport.h if viewport.h > 0 else 0
    back_w = background.w if background.w > 0 else 0
    back_h = background.h if background.h > 0 else 0
    tile_h = back_h if back_h < view_h else view_h
    tiles: list[MarqueeTile] = []
    if back_w > 0 and tile_h > 0 and view_w > 0:
        offset = t % back_w
        x = 0
        src = offset
        while x < view_w:
            run = back_w - src
            if run > view_w - x:
                run = view_w - x
            tiles.append(MarqueeTile(x, 0, run, tile_h, src, 0))
            x += run
            src = 0
    return HMarquee(view_w, view_h, tuple(tiles))
