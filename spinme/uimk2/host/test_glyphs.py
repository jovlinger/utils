"""Host tests for gen_glyphs: box height, baseline, ink widths, fresh render."""

import os
import unittest

from PIL import Image, ImageDraw, ImageFont

import gen_glyphs as g

FONT = "/System/Library/Fonts/Helvetica.ttc"
PX = 12


def _rows(table, ch):
    """Alpha rows of one glyph from the table, as lists of ints."""
    for cp, width, offset in table.entries:
        if cp == ord(ch):
            return [
                list(table.alpha[offset + r * width:offset + (r + 1) * width])
                for r in range(table.height)
            ]
    raise KeyError(ch)


def _fresh_box(font, ch, px, height, baseline):
    """Re-render ch with the pen at a different origin and cut it again.

    The origin is shifted by two pixels, so the box must not depend on where
    the pen sits. Ink columns come from the sample-level bounding box.
    """
    shift = 2 * g.SUB * px
    cols = shift + 3 * g.SUB * px
    rows = height * g.SUB
    im = Image.new("1", (cols, rows), 0)
    ImageDraw.Draw(im).text(
        (shift, baseline * g.SUB), ch, font=font, fill=1, anchor="ls"
    )
    box = im.getbbox()
    if box is None:
        return None
    left, top, right, bottom = box
    assert top >= 0 and bottom <= rows, "ink outside the H-row box"
    first = left // g.SUB
    last = (right - 1) // g.SUB
    out = []
    for r in range(height):
        row = []
        for c in range(first, last + 1):
            filled = 0
            for sy in range(r * g.SUB, r * g.SUB + g.SUB):
                for sx in range(c * g.SUB, c * g.SUB + g.SUB):
                    if im.getpixel((sx, sy)):
                        filled += 1
            row.append(filled * 255 // 64)
        out.append(row)
    return out


@unittest.skipUnless(os.path.exists(FONT), "Helvetica not installed")
class GlyphTableTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.table = g.build(FONT, PX)
        cls.font = ImageFont.truetype(FONT, g.SUB * PX, index=0)

    def test_every_box_has_height_h(self):
        t = self.table
        self.assertGreater(t.baseline, 0)
        self.assertLess(t.baseline, t.height)
        for cp, width, offset in t.entries:
            self.assertGreater(width, 0, chr(cp))
            self.assertEqual(len(t.alpha[offset:offset + width * t.height]),
                             width * t.height, chr(cp))
            rows = _rows(t, chr(cp))
            self.assertEqual(len(rows), t.height)
            self.assertEqual(len(rows[0]), width)

    def test_offsets_are_contiguous(self):
        end = 0
        for _, width, offset in self.table.entries:
            self.assertEqual(offset, end)
            end += width * self.table.height
        self.assertEqual(end, len(self.table.alpha))

    def test_baseline_row(self):
        t = self.table
        # 'x' has no descender: its last ink row is the row above the baseline.
        x_rows = _rows(t, "x")
        last_ink = max(r for r, row in enumerate(x_rows) if any(row))
        self.assertEqual(last_ink, t.baseline - 1)
        # 'g' has a descender: its last ink row is below the baseline.
        g_rows = _rows(t, "g")
        g_last = max(r for r, row in enumerate(g_rows) if any(row))
        self.assertGreater(g_last, t.baseline - 1)

    def test_box_is_tight_to_all_glyphs(self):
        t = self.table
        top_used = bottom_used = False
        for cp, _, _ in t.entries:
            rows = _rows(t, chr(cp))
            top_used = top_used or any(rows[0])
            bottom_used = bottom_used or any(rows[t.height - 1])
        self.assertTrue(top_used, "no glyph reaches row 0")
        self.assertTrue(bottom_used, "no glyph reaches row H-1")

    def test_widths_are_ink_span(self):
        t = self.table
        for cp, width, _ in t.entries:
            fresh = _fresh_box(self.font, chr(cp), PX, t.height, t.baseline)
            if fresh is None:
                continue
            self.assertEqual(width, len(fresh[0]), chr(cp))
            rows = _rows(t, chr(cp))
            self.assertTrue(any(row[0] for row in rows), chr(cp))
            self.assertTrue(any(row[-1] for row in rows), chr(cp))

    def test_boxes_match_fresh_render(self):
        t = self.table
        for cp, _, _ in t.entries:
            ch = chr(cp)
            fresh = _fresh_box(self.font, ch, PX, t.height, t.baseline)
            if fresh is None:
                continue
            self.assertEqual(_rows(t, ch), fresh, ch)

    def test_alpha_values_are_filled_times_255_over_64(self):
        allowed = {n * 255 // 64 for n in range(65)}
        for b in self.table.alpha:
            self.assertIn(b, allowed)

    def test_space_takes_advance_width(self):
        t = self.table
        for cp, width, offset in t.entries:
            if cp == ord(" "):
                self.assertGreater(width, 0)
                blank = t.alpha[offset:offset + width * t.height]
                self.assertFalse(any(blank))
                return
        self.fail("space missing from table")

    def test_fallback_present(self):
        cps = {cp for cp, _, _ in self.table.entries}
        self.assertIn(ord(g.FALLBACK), cps)


if __name__ == "__main__":
    unittest.main()
