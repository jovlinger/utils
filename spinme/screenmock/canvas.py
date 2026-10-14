"""RGB565 framebuffer with the classic GFX 5x7 cursor rules."""

from __future__ import annotations

from PIL import Image, ImageDraw

from screenmock.font5x7 import FONT5X7

WIDTH = 360
HEIGHT = 360
CENTER = WIDTH // 2
RADIUS = WIDTH // 2
GLYPH_W = 6
GLYPH_H = 8

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


class Canvas:
    """Square panel buffer. Text matches GFX glcdfont at the given size."""

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
        cursor_x = x
        for ch in s:
            code = ord(ch)
            if code < 0 or code > 255:
                code = ord("?")
            base = code * 5
            for col in range(5):
                bits = FONT5X7[base + col]
                for row in range(8):
                    if bits & (1 << row):
                        self.fill_rect(
                            cursor_x + col * size,
                            y + row * size,
                            size,
                            size,
                            color,
                        )
            cursor_x += GLYPH_W * size

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
