"""Host tests for gen_glyphs.py: read the generated C table back and check
every box against a fresh render of the font.

The fresh render goes through FreeTypeFont.getmask2 (bilevel, baseline
anchored) and cuts its own 8x8 grid; it shares no code with the generator.
"""

import os
import re
import subprocess
import sys
import tempfile
import unittest

from PIL import ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "gen_glyphs.py")
FONT = "/System/Library/Fonts/Helvetica.ttc"
SIZES = (12, 24)
SS = 8
ALLOWED_ALPHA = {f * 255 // 64 for f in range(65)}


def ceil_div(a, b):
    return -(-a // b)


def parse_table(src):
    def scalar(name):
        m = re.search(r"const uint16_t %s = (\d+);" % name, src)
        return int(m.group(1))

    table = [
        (int(cp, 16), int(w), int(off))
        for cp, w, off in re.findall(r"\{0x([0-9A-F]+), (\d+), (\d+)\},", src)
    ]
    body = src.split("uimk2_glyph_alpha[")[1].split("{", 1)[1].split("}")[0]
    alpha = bytes(int(v) for v in re.findall(r"\d+", body))
    return (
        scalar("uimk2_glyph_h"),
        scalar("uimk2_glyph_b"),
        scalar("uimk2_glyph_count"),
        table,
        alpha,
    )


def fresh_ink(font, ch):
    """Set of inked samples (x, y) relative to the baseline origin."""
    mask, (mx, my) = font.getmask2(ch, mode="1", anchor="ls")
    w, h = mask.size
    ink = set()
    for y in range(h):
        for x in range(w):
            if mask.getpixel((x, y)):
                ink.add((mx + x, my + y))
    return ink


class GlyphTableTest(unittest.TestCase):
    def check_size(self, px):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "glyphs.c")
            subprocess.run([sys.executable, GEN, FONT, str(px), out], check=True)
            with open(out, "rb") as f:
                raw = f.read()
        self.assertTrue(all(c < 0x80 for c in raw), "output is not ASCII")
        h, b, count, table, alpha = parse_table(raw.decode("ascii"))

        font = ImageFont.truetype(FONT, px * SS)
        cps = [cp for cp, _, _ in table]
        self.assertEqual(cps, list(range(0x20, 0x7F)))
        self.assertEqual(count, len(table))
        self.assertIn(ord("?"), cps)

        inks = {cp: fresh_ink(font, chr(cp)) for cp in cps}
        asc = max(-y for ink in inks.values() for _, y in ink)
        desc = max(y + 1 for ink in inks.values() for _, y in ink)
        self.assertEqual(b, ceil_div(asc, SS))
        self.assertEqual(h, ceil_div(asc, SS) + ceil_div(desc, SS))

        offset = 0
        top_row_ink = False
        bottom_row_ink = False
        for cp, width, off in table:
            self.assertEqual(off, offset, "offsets are contiguous")
            box = alpha[off : off + width * h]
            self.assertEqual(len(box), width * h)
            offset += width * h
            ink = inks[cp]
            if not ink:
                adv = int(round(font.getlength(chr(cp)) / SS))
                self.assertEqual(width, adv, "no-ink width is the advance")
                self.assertEqual(box, bytes(width * h))
                continue
            xmin = min(x for x, _ in ink)
            xmax = max(x for x, _ in ink)
            self.assertEqual(
                width,
                ceil_div(xmax + 1 - xmin, SS),
                "width of %r is its ink span" % chr(cp),
            )
            # Tight: the first and the last column hold ink.
            self.assertTrue(any(box[r * width] for r in range(h)))
            self.assertTrue(any(box[r * width + width - 1] for r in range(h)))
            top_row_ink |= any(box[:width])
            bottom_row_ink |= any(box[(h - 1) * width :])
            # Every inked sample lies inside the H-row box.
            for x, y in ink:
                self.assertTrue(-b * SS <= y < (h - b) * SS)
            for r in range(h):
                for c in range(width):
                    filled = 0
                    y0 = -b * SS + r * SS
                    x0 = xmin + c * SS
                    for sy in range(y0, y0 + SS):
                        for sx in range(x0, x0 + SS):
                            if (sx, sy) in ink:
                                filled += 1
                    self.assertEqual(
                        box[r * width + c],
                        filled * 255 // 64,
                        "%r row %d col %d" % (chr(cp), r, c),
                    )
        self.assertEqual(offset, len(alpha))
        self.assertTrue(set(alpha) <= ALLOWED_ALPHA)
        # Smallest box: some glyph inks row 0 and some inks row H - 1.
        self.assertTrue(top_row_ink)
        self.assertTrue(bottom_row_ink)
        # Baseline row: 'H' sits on it, 'g' descends below it.
        hb = dict((cp, (w, o)) for cp, w, o in table)
        w, o = hb[ord("H")]
        self.assertTrue(any(alpha[o + (b - 1) * w : o + b * w]))
        self.assertFalse(any(alpha[o + b * w : o + h * w]))
        w, o = hb[ord("g")]
        self.assertTrue(any(alpha[o + b * w : o + h * w]))

    def test_size_12(self):
        self.check_size(12)

    def test_size_24(self):
        self.check_size(24)


if __name__ == "__main__":
    unittest.main()
