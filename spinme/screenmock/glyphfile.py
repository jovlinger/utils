"""Glyph file shared by the glass mock and the ESP32 image.

The file is a little-endian array of glyph structs. Each struct holds a
key, a tight box of the shared body height, and row-major RGBA.
Letter, word, line, and section gaps are not glyphs. They are zero-area
shim boxes, predefined in the header and inserted into l2r / t2b.

On the ESP32 the same bytes are linked into flash and mapped. This
loader is the host-side view of that file.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from screenmock.compose import Box, VAlign, l2r

BODY_H = 36
LETTER_HSHIM = 3
WORD_HSHIM = 12
LINE_VSHIM = 3
SECTION_VSHIM = 18
MAGIC = 0x31594C47
VERSION = 1

_HEADER = struct.Struct("<10I")
_INDEX = struct.Struct("<II")
_REC = struct.Struct("<IhhHH")

BIN = (
    Path(__file__).resolve().parents[1]
    / "firmware/waveshare-knob-touch-lcd-1.8/glyphs.bin"
)


@dataclass(frozen=True)
class Glyph:
    key: int
    x: int
    y: int
    w: int
    h: int
    rgba: bytes


@dataclass(frozen=True)
class GlyphFile:
    height: int
    letter_hshim: int
    word_hshim: int
    line_vshim: int
    section_vshim: int
    glyphs: dict[int, Glyph]


def save(path: Path, glyphs: list[Glyph]) -> None:
    ordered = sorted(glyphs, key=lambda item: item.key)
    index_off = _HEADER.size
    cursor = index_off + len(ordered) * _INDEX.size
    index_blob = bytearray()
    rec_blob = bytearray()
    for glyph in ordered:
        if glyph.h != BODY_H:
            raise SystemExit("glyph height {0} is not the shared body".format(glyph.h))
        if len(glyph.rgba) != glyph.w * glyph.h * 4:
            raise SystemExit("rgba length does not match the box")
        index_blob += _INDEX.pack(glyph.key, cursor)
        rec_blob += _REC.pack(glyph.key, glyph.x, glyph.y, glyph.w, glyph.h)
        rec_blob += glyph.rgba
        cursor += _REC.size + len(glyph.rgba)
    header = _HEADER.pack(
        MAGIC,
        VERSION,
        len(ordered),
        BODY_H,
        LETTER_HSHIM,
        WORD_HSHIM,
        LINE_VSHIM,
        SECTION_VSHIM,
        index_off,
        0,
    )
    path.write_bytes(header + bytes(index_blob) + bytes(rec_blob))


def load(path: Path | None = None) -> GlyphFile:
    blob = (path if path is not None else BIN).read_bytes()
    if len(blob) < _HEADER.size:
        raise SystemExit("glyph file is shorter than its header")
    (
        magic,
        version,
        count,
        height,
        letter,
        word,
        line,
        section,
        index_off,
        _reserved,
    ) = _HEADER.unpack_from(blob, 0)
    if magic != MAGIC or version != VERSION:
        raise SystemExit("glyph file magic does not match")
    glyphs: dict[int, Glyph] = {}
    for i in range(count):
        key, offset = _INDEX.unpack_from(blob, index_off + i * _INDEX.size)
        rec_key, x, y, w, h = _REC.unpack_from(blob, offset)
        if rec_key != key or h != height:
            raise SystemExit("glyph record does not match the index")
        start = offset + _REC.size
        rgba = blob[start : start + w * h * 4]
        glyphs[key] = Glyph(key, x, y, w, h, rgba)
    return GlyphFile(height, letter, word, line, section, glyphs)


_cached: GlyphFile | None = None


def mapped() -> GlyphFile:
    global _cached
    if _cached is None:
        _cached = load(BIN)
    return _cached


def letter_hshim() -> Box:
    return Box(mapped().letter_hshim, 0)


def word_hshim() -> Box:
    return Box(mapped().word_hshim, 0)


def line_vshim() -> Box:
    return Box(0, mapped().line_vshim)


def section_vshim() -> Box:
    return Box(0, mapped().section_vshim)


def text_items(text: str) -> list[tuple[Box, Glyph | None]]:
    """Glyph boxes and the shims that separate them. Shims carry no glyph."""
    face = mapped()
    items: list[tuple[Box, Glyph | None]] = []
    prev_glyph = False
    for ch in text:
        if ch == " ":
            items.append((Box(face.word_hshim, 0), None))
            prev_glyph = False
            continue
        glyph = face.glyphs.get(ord(ch))
        if glyph is None:
            glyph = face.glyphs.get(ord("?"))
        if glyph is None:
            continue
        if prev_glyph:
            items.append((Box(face.letter_hshim, 0), None))
        items.append((Box(glyph.w, glyph.h), glyph))
        prev_glyph = True
    return items


def line_box(text: str) -> Box | None:
    items = text_items(text)
    if not any(glyph is not None for _box, glyph in items):
        return None
    union = l2r([box for box, _glyph in items], VAlign.bot)
    return Box(union.w, union.h)


def text_width(text: str) -> int:
    box = line_box(text)
    if box is None:
        return 0
    return box.w
