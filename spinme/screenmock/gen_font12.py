#!/usr/bin/env venv-run
"""Rasterize DejaVu Sans into the mmap glyph file.

Each glyph is a tight box of the shared 36px body height and an RGBA
image (white RGB, alpha = sample coverage). Gaps are shims in the file
header, not pixels in the glyph.

Usage: gen_font12.py /path/to/DejaVuSans.ttf
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screenmock.glyphfile import BIN, BODY_H, Glyph, save

INK_H = BODY_H
SAMPLES = 8
SPAN = INK_H * SAMPLES
FIRST = 32
LAST = 126


def font_for_body(path: str) -> ImageFont.FreeTypeFont:
    best: ImageFont.FreeTypeFont | None = None
    for size in range(SPAN, 40, -1):
        font = ImageFont.truetype(path, size)
        ascent, descent = font.getmetrics()
        if ascent + descent <= SPAN:
            best = font
            break
    if best is None:
        raise SystemExit("no DejaVu size fits a {0}px body".format(INK_H))
    ascent, descent = best.getmetrics()
    if ascent + descent != SPAN:
        raise SystemExit(
            "body span is {0}, want {1}".format(ascent + descent, SPAN)
        )
    return best


def raster(font: ImageFont.FreeTypeFont, ch: str) -> Glyph | None:
    ascent, _descent = font.getmetrics()
    columns = max(1, int(round(font.getlength(ch) / SAMPLES)))
    image = Image.new("1", (columns * SAMPLES + SAMPLES, SPAN), 0)
    draw = ImageDraw.Draw(image)
    draw.text((0, ascent), ch, font=font, fill=1, anchor="ls")
    pixels = image.load()
    assert pixels is not None
    max_col = image.width // SAMPLES
    ink = [False] * max_col
    for col in range(max_col):
        x0 = col * SAMPLES
        for row in range(INK_H):
            y0 = row * SAMPLES
            hit = False
            for yy in range(SAMPLES):
                for xx in range(SAMPLES):
                    if pixels[x0 + xx, y0 + yy]:
                        hit = True
                        break
                if hit:
                    break
            if hit:
                ink[col] = True
                break
    if True not in ink:
        return None
    first = ink.index(True)
    last = len(ink) - 1 - ink[::-1].index(True)
    width = last - first + 1
    raw = bytearray()
    scale = SAMPLES * SAMPLES
    for row in range(INK_H):
        y0 = row * SAMPLES
        for col in range(first, last + 1):
            x0 = col * SAMPLES
            filled = 0
            for yy in range(SAMPLES):
                for xx in range(SAMPLES):
                    if pixels[x0 + xx, y0 + yy]:
                        filled += 1
            alpha = filled * 255 // scale
            raw.extend((255, 255, 255, alpha))
    return Glyph(ord(ch), 0, 0, width, INK_H, bytes(raw))


def emit(font: ImageFont.FreeTypeFont) -> None:
    glyphs: list[Glyph] = []
    for code in range(FIRST, LAST + 1):
        glyph = raster(font, chr(code))
        if glyph is not None:
            glyphs.append(glyph)
    if ord("?") not in {glyph.key for glyph in glyphs}:
        raise SystemExit("missing '?' glyph")
    save(BIN, glyphs)
    print("glyphs {0} -> {1}".format(len(glyphs), BIN))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: gen_font12.py DejaVuSans.ttf")
    emit(font_for_body(sys.argv[1]))


if __name__ == "__main__":
    main()
