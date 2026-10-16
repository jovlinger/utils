"""RGB framebuffer. Text is the mapped DejaVu glyph file."""

from __future__ import annotations

from PIL import Image, ImageDraw

from screenmock.compose import VAlign, l2r
from screenmock.glyphfile import text_items, text_width as glyph_text_width

WIDTH = 360
HEIGHT = 360
CENTER = WIDTH // 2
RADIUS = WIDTH // 2
GLYPH_W = 6
GLYPH_H = 36

Rgb = tuple[int, int, int]
BLACK: Rgb = (0, 0, 0)


def rgb565(red: int, green: int, blue: int) -> Rgb:
    """Match Arduino_GFX RGB565(), then expand back to 8-bit channels."""
    packed = ((red & 0xF8) << 8) | ((green & 0xFC) << 3) | (blue >> 3)
    return (
        (packed >> 11) << 3,
        ((packed >> 5) & 0x3F) << 2,
        (packed & 0x1F) << 3,
    )


YELLOW: Rgb = rgb565(255, 255, 0)
WHITE: Rgb = rgb565(255, 255, 255)
BEZEL: Rgb = (32, 32, 36)


def in_circle(x: int, y: int, radius: int = RADIUS, center: int = CENTER) -> bool:
    dx = x - center
    dy = y - center
    return dx * dx + dy * dy <= radius * radius


def box_inside_circle(x: int, y: int, w: int, h: int) -> bool:
    if w <= 0 or h <= 0:
        return True
    for px in (x, x + w - 1):
        for py in (y, y + h - 1):
            if not in_circle(px, py):
                return False
    return True


def text_width(s: str) -> int:
    return glyph_text_width(s)


def _blend(dst: Rgb, src: Rgb, alpha: int) -> Rgb:
    if alpha <= 0:
        return dst
    if alpha >= 255:
        return src
    inv = 255 - alpha
    return tuple((src[i] * alpha + dst[i] * inv) // 255 for i in range(3))


class Canvas:
    """Square panel buffer. Glyphs come from the mapped RGBA file."""

    def __init__(self, width: int = WIDTH, height: int = HEIGHT) -> None:
        self.image = Image.new("RGB", (width, height), BLACK)
        self._px = self.image.load()

    def fill(self, color: Rgb) -> None:
        self.image.paste(color, (0, 0, self.image.width, self.image.height))

    def fill_rect(self, x: int, y: int, w: int, h: int, color: Rgb) -> None:
        for py in range(y, y + h):
            if py < 0 or py >= self.image.height:
                continue
            for px in range(x, x + w):
                if 0 <= px < self.image.width:
                    self._px[px, py] = color

    def text(self, s: str, x: int, y: int, size: int, color: Rgb) -> None:
        del size
        items = text_items(s)
        if not items:
            return
        union = l2r([box for box, _glyph in items], VAlign.bot)
        for child, (_box, glyph) in zip(union.children, items):
            if glyph is None:
                continue
            left = x + child.left() - union.x
            top = y + child.top() - union.y
            for row in range(glyph.h):
                py = top + row
                for col in range(glyph.w):
                    alpha = glyph.rgba[(row * glyph.w + col) * 4 + 3]
                    if alpha == 0:
                        continue
                    px = left + col
                    if 0 <= px < self.image.width and 0 <= py < self.image.height:
                        self._px[px, py] = _blend(self._px[px, py], color, alpha)

    def ink_outside_circle(self, background: Rgb = BLACK) -> int:
        count = 0
        width, height = self.image.size
        for y in range(height):
            for x in range(width):
                if self._px[x, y] != background and not in_circle(x, y):
                    count += 1
        return count


def round_preview(square: Image.Image) -> Image.Image:
    """Show the glass. Pixels outside the circle stay visible, dimmed on the bezel."""
    preview = Image.new("RGB", square.size, BEZEL)
    src = square.load()
    dst = preview.load()
    width, height = square.size
    for y in range(height):
        for x in range(width):
            pixel = src[x, y]
            if in_circle(x, y):
                dst[x, y] = pixel
            else:
                dst[x, y] = tuple((pixel[i] + BEZEL[i] * 3) // 4 for i in range(3))
    draw = ImageDraw.Draw(preview)
    draw.ellipse((0, 0, width - 1, height - 1), outline=(255, 96, 0))
    return preview
