"""l2r and t2b place children around the center of their tight union."""

from __future__ import annotations

from screenmock.compose import Box, HAlign, VAlign, hmarquee, hshim, l2r, t2b, vshim
from screenmock.glyphfile import (
    LETTER_HSHIM,
    LINE_VSHIM,
    SECTION_VSHIM,
    WORD_HSHIM,
    letter_hshim,
    line_vshim,
    load,
    section_vshim,
    text_width,
    word_hshim,
)
from screenmock.layout import fitted_line_boxes


def _bottom(cx_unused: int, placed_cy: int, h: int) -> int:
    del cx_unused
    return (placed_cy - h // 2) + h


def test_l2r_bot_shares_a_bottom_and_the_origin_is_the_center() -> None:
    union = l2r([Box(10, 20), Box(8, 12)], VAlign.bot)
    assert (union.w, union.h) == (18, 20)
    assert union.x + union.w // 2 == 0
    assert union.y + union.h // 2 == 0
    bottoms = [_bottom(0, child.cy, child.h) for child in union.children]
    assert bottoms[0] == bottoms[1]


def test_l2r_vcenter_shares_the_cross_axis_center() -> None:
    union = l2r([Box(4, 20), Box(4, 10)], VAlign.vcenter)
    assert union.children[1].cy == 0


def test_l2r_top_pins_the_short_box_to_the_top() -> None:
    union = l2r([Box(4, 20), Box(4, 10)], VAlign.top)
    assert union.children[1].top() == union.y


def test_t2b_left_shares_a_left_edge() -> None:
    union = t2b([Box(10, 4), Box(4, 6)], HAlign.left)
    assert union.children[0].left() == union.children[1].left()
    assert union.x + union.w // 2 == 0
    assert union.y + union.h // 2 == 0


def test_t2b_right_shares_a_right_edge() -> None:
    union = t2b([Box(10, 4), Box(4, 6)], HAlign.right)
    right0 = union.children[0].left() + union.children[0].w
    right1 = union.children[1].left() + union.children[1].w
    assert right0 == right1


def test_shims_are_zero_area_boxes() -> None:
    assert hshim(4).w == 4 and hshim(4).h == 0
    assert vshim(5).w == 0 and vshim(5).h == 5
    for box in (letter_hshim(), word_hshim(), line_vshim(), section_vshim()):
        assert box.w * box.h == 0
        assert box.w > 0 or box.h > 0
    face = load()
    glyph = face.glyphs[ord("H")]
    assert glyph.h == face.height
    assert len(glyph.rgba) == glyph.w * glyph.h * 4
    assert ord(" ") not in face.glyphs
    assert face.letter_hshim == LETTER_HSHIM
    assert face.word_hshim == WORD_HSHIM
    assert face.line_vshim == LINE_VSHIM
    assert face.section_vshim == SECTION_VSHIM
    assert word_hshim().w > letter_hshim().w
    assert section_vshim().h > line_vshim().h


def test_word_shim_is_wider_than_the_letter_shim() -> None:
    assert text_width("a b") - text_width("ab") == WORD_HSHIM - LETTER_HSHIM


def test_section_shim_is_taller_than_the_line_shim() -> None:
    rects = fitted_line_boxes(["aa", "bb", "cc"], [0, 0, 1])
    gap_line = rects[1][1] - (rects[0][1] + rects[0][3])
    gap_section = rects[2][1] - (rects[1][1] + rects[1][3])
    assert gap_line == LINE_VSHIM
    assert gap_section == SECTION_VSHIM


def test_hmarquee_viewport_is_the_external_box() -> None:
    mark = hmarquee(Box(7, 4), Box(10, 9), 0)
    assert (mark.w, mark.h) == (7, 4)
    assert len(mark.tiles) == 1
    assert (mark.tiles[0].x, mark.tiles[0].src_x, mark.tiles[0].w) == (0, 0, 7)
    assert mark.tiles[0].h == 4


def test_hmarquee_wraps_without_a_seam() -> None:
    mark = hmarquee(Box(7, 4), Box(10, 4), 8)
    assert len(mark.tiles) == 2
    head, tail = mark.tiles
    assert head.x + head.w == tail.x
    assert head.src_x + head.w == 10
    assert tail.src_x == 0
    assert head.w + tail.w == 7
    assert hmarquee(Box(7, 4), Box(10, 4), 10).tiles == hmarquee(Box(7, 4), Box(10, 4), 0).tiles


def test_hmarquee_tiles_a_short_background_across_the_viewport() -> None:
    mark = hmarquee(Box(10, 3), Box(4, 3), 0)
    assert [tile.w for tile in mark.tiles] == [4, 4, 2]
    assert mark.tiles[0].x + mark.tiles[0].w == mark.tiles[1].x
    assert mark.tiles[1].src_x == 0


def test_english_lines_are_left_aligned_and_vcentered() -> None:
    rects = fitted_line_boxes(["short", "a much longer line of text"])
    assert len(rects) == 2
    assert rects[0][0] == rects[1][0]
    short_cx = rects[0][0] + rects[0][2] // 2
    assert short_cx != 180
    top = min(rect[1] for rect in rects)
    bottom = max(rect[1] + rect[3] for rect in rects)
    assert (top + bottom) // 2 == 180
