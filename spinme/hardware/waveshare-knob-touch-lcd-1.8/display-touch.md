# Display and touch -- Waveshare Knob-Touch-LCD-1.8

Summary extracted from recovered board research ([README.md](README.md)).

## Circular bezel, square framebuffer

Physically round 1.8" IPS; controller framebuffer is **360x360** (ST77916 over
QSPI). Same square-in-circle pattern as the Elecrow CrowPanel, different IC and
resolution.

## Stack

| Layer | Notes |
|-------|-------|
| LVGL | UI widgets; S3 demos use LVGL |
| Panel | ST77916 QSPI (not GC9A01 SPI) |
| Touch | CST816 I2C |

Arduino demo pins (S3), from research notes: CS=14, PCLK=13, DATA0-3=15,16,17,18,
RST=21, backlight=47.

LVGL rotation: 180 deg is cheap; 90/270 need transpose (slow). Prefer bitmap fonts
over TinyTTF on S3.

Do not reuse Elecrow CrowPanel pin headers or GC9A01 init on this board.
