#!/usr/bin/env python3
"""Reads the generated table and checks every box against a fresh render."""
import os
import re
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

import glyphgen

FONT = "/System/Library/Fonts/Helvetica.ttc"
SIZE = 24
SS = glyphgen.SS


def parse_header(path):
    with open(path, encoding="ascii") as f:
        text = f.read()
    h = int(re.search(r"#define GLYPH_H (\d+)", text).group(1))
    b = int(re.search(r"#define GLYPH_B (\d+)", text).group(1))
    table = [(int(c, 16), int(w), int(o))
             for c, w, o in re.findall(r"\{(0x[0-9A-F]+), (\d+), (\d+)\},", text)]
    body = text.split("glyph_alpha[")[1].split("{", 1)[1].rsplit("}", 1)[0]
    blob = [int(v) for v in re.findall(r"\d+", body)]
    return h, b, table, blob


class GlyphGenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "glyphs.h")
        assert glyphgen.main(["x", FONT, str(SIZE), out]) == 0
        cls.h, cls.b, cls.table, cls.blob = parse_header(out)
        cls.font = glyphgen.load_font(FONT, SIZE)

    def fresh_box(self, ch):
        """Independent render: full ink of one glyph on a big canvas, baseline at row b."""
        pad, wide = SIZE, SIZE * 4
        img = Image.new("1", (wide * SS, self.h * SS), 0)
        dr = ImageDraw.Draw(img)
        dr.fontmode = "1"
        dr.text((pad * SS, self.b * SS), ch, font=self.font, fill=1, anchor="ls")
        px = img.load()
        cols = []
        for x in range(wide):
            col = []
            for y in range(self.h):
                n = sum(1 for yy in range(SS) for xx in range(SS)
                        if px[x * SS + xx, y * SS + yy])
                col.append(n * 255 // 64)
            cols.append(col)
        return cols

    def test_height_and_baseline(self):
        self.assertGreater(self.h, self.b)
        self.assertGreater(self.b, 0)
        # tightest box: some glyph touches the top row and some the bottom row
        top = bottom = False
        for _cp, w, off in self.table:
            for x in range(w):
                if self.blob[off + x]:
                    top = True
                if self.blob[off + (self.h - 1) * w + x]:
                    bottom = True
        self.assertTrue(top and bottom)

    def test_baseline_row(self):
        # 'H' sits on the baseline: ink in row b-1, none in row b.
        cp, w, off = [e for e in self.table if e[0] == ord("H")][0]
        row = lambda r: self.blob[off + r * w: off + (r + 1) * w]
        self.assertTrue(any(row(self.b - 1)))
        if self.b < self.h:
            self.assertFalse(any(row(self.b)))
        # 'p' descends below the baseline
        cp, w, off = [e for e in self.table if e[0] == ord("p")][0]
        self.assertTrue(any(self.blob[off + r * w + x] for r in range(self.b, self.h)
                            for x in range(w)))

    def test_all_boxes_match_fresh_render(self):
        self.assertEqual(len(self.table), 0x7F - 0x20)
        for cp, w, off in self.table:
            ch = chr(cp)
            cols = self.fresh_box(ch)
            inked = [x for x, c in enumerate(cols) if any(c)]
            if inked:
                lo, hi = inked[0], inked[-1]
                self.assertEqual(w, hi - lo + 1, repr(ch))
            else:
                lo = 0
                self.assertEqual(w, max(1, round(self.font.getlength(ch) / SS)), repr(ch))
                self.assertTrue(w >= 1)
            for y in range(self.h):
                for x in range(w):
                    exp = cols[lo + x][y] if inked else 0
                    self.assertEqual(self.blob[off + y * w + x], exp, (ch, x, y))

    def test_space_has_advance_and_no_ink(self):
        cp, w, off = [e for e in self.table if e[0] == 0x20][0]
        self.assertGreater(w, 0)
        self.assertEqual(sum(self.blob[off: off + w * self.h]), 0)

    def test_offsets_contiguous(self):
        pos = 0
        for _cp, w, off in self.table:
            self.assertEqual(off, pos)
            pos += w * self.h
        self.assertEqual(pos, len(self.blob))

    def test_question_mark_present_and_ascii(self):
        self.assertIn(ord("?"), [e[0] for e in self.table])


if __name__ == "__main__":
    unittest.main()
