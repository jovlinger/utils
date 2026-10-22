#!/usr/bin/env python3
"""Host test for genglyphs.py: generate a table, read it back, and check it
against an independent fresh render. usage: test_glyphs.py [FONT] [SIZE]"""
import os
import re
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont

import genglyphs

FONT = sys.argv[1] if len(sys.argv) > 1 else "/System/Library/Fonts/Helvetica.ttc"
SIZE = int(sys.argv[2]) if len(sys.argv) > 2 else 24


def parse_header(path):
    text = open(path, encoding="ascii").read()
    h = int(re.search(r"#define GLYPH_H (\d+)", text).group(1))
    b = int(re.search(r"#define GLYPH_B (\d+)", text).group(1))
    ents = [tuple(int(v) for v in m) for m in
            re.findall(r"\{(\d+), (\d+), (\d+)\},", text)]
    blob_txt = text.split("kGlyphAlpha[")[1].split("{", 1)[1].split("}")[0]
    blob = bytes(int(v) for v in re.findall(r"\d+", blob_txt))
    return h, b, ents, blob


def fresh_box(font, ch, h, b):
    """Independent render: full-width grid, count per 8x8, trim to ink."""
    adv = int(font.getlength(ch))
    gw = ((8 * 8 + adv) // 8 + 2) * 8
    img = Image.new("L", (gw, h * 8), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    d.text((32, b * 8), ch, font=font, fill=255, anchor="ls")
    px = img.load()
    cols = gw // 8
    alpha = [[sum(1 for gy in range(8) for gx in range(8)
                  if px[c * 8 + gx, r * 8 + gy]) * 255 // 64
              for c in range(cols)] for r in range(h)]
    return alpha


def main():
    failures = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory() as td:
        out = os.path.join(td, "g.h")
        info = genglyphs.build(FONT, SIZE)
        genglyphs.emit_header(info, out)
        raw = open(out, "rb").read()
        check(all(c < 128 for c in raw), "output is not ASCII")
        h, b, ents, blob = parse_header(out)

    font = ImageFont.truetype(FONT, SIZE * 8, index=0)

    # metrics: smallest box holding every ink extent
    asc = max(-font.getbbox(chr(c), anchor="ls")[1]
              for c in range(0x21, 0x7F))
    desc = max(font.getbbox(chr(c), anchor="ls")[3]
               for c in range(0x21, 0x7F))
    ea, ed = -(-asc // 8), -(-desc // 8)
    check(h == ea + ed, "H %d != ascent+descent %d" % (h, ea + ed))
    check(b == ea, "B %d != ascent %d" % (b, ea))
    check(len(ents) == 0x7F - 0x20, "entry count %d" % len(ents))

    off = 0
    for cp, width, offset in ents:
        ch = chr(cp)
        check(offset == off, "offset gap at %r" % ch)
        off += width * h
        box = [list(blob[offset + r * width: offset + (r + 1) * width])
               for r in range(h)]
        full = fresh_box(font, ch, h, b)
        ink = [c for c in range(len(full[0]))
               if any(full[r][c] for r in range(h))]
        if ink:
            lo, hi = ink[0], ink[-1]
            check(width == hi - lo + 1, "width of %r: %d vs span %d"
                  % (ch, width, hi - lo + 1))
            want = [row[lo:hi + 1] for row in full]
            check(box == want, "box mismatch for %r" % ch)
            # ink on the first and last column
            check(any(box[r][0] for r in range(h)), "no ink col 0 %r" % ch)
            check(any(box[r][-1] for r in range(h)), "no ink last col %r" % ch)
        else:
            adv = max(1, round(font.getlength(ch) / 8))
            check(width == adv, "space width %d vs advance %d" % (width, adv))
            check(not any(blob[offset:offset + width * h]), "space has ink")
        # alpha values are filled*255/64
        for v in blob[offset:offset + width * h]:
            check(any(v == f * 255 // 64 for f in range(65)),
                  "alpha %d not filled*255/64 for %r" % (v, ch))

    check(off == len(blob), "blob length %d vs table %d" % (len(blob), off))
    # baseline row: 'H' has no descender, so its ink ends on row B-1
    cp, width, offset = next(e for e in ents if e[0] == ord("H"))
    rows_with_ink = [r for r in range(h)
                     if any(blob[offset + r * width: offset + (r + 1) * width])]
    check(rows_with_ink[-1] == b - 1, "H bottom row %d, B %d"
          % (rows_with_ink[-1], b))
    # 'g' descends below the baseline
    cp, width, offset = next(e for e in ents if e[0] == ord("g"))
    check(any(blob[offset + (h - 1) * width: offset + h * width]),
          "g has no ink on the last row")

    for f in failures[:20]:
        print("FAIL", f)
    if failures:
        print("%d failures" % len(failures))
        return 1
    print("test_glyphs: ok H=%d B=%d glyphs=%d bytes=%d"
          % (h, b, len(ents), len(blob)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
