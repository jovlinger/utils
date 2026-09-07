# Display and touch programming model

Board: CrowPanel 1.28" rotary (SKU DHE38128D). See `hardware-identity.md`.

## Circular bezel, square framebuffer

The panel is physically round, but the controller exposes a **240 x 240** square
framebuffer (GC9A01). Corners of the square are outside the visible circle; UI
code either:

- draws full-screen widgets and accepts clipped corners, or
- masks to a circle / designs radial layouts that stay inside the inscribed disk.

There is no separate "circular resolution." Square pixels, round optics.

## Implied stack (what Elecrow actually ships)

Not a mysterious proprietary UI OS. The poorly advertised but real stack is:

```text
App  ->  LVGL (widgets)  ->  LovyanGFX / Arduino_GFX (pixels + panel init)
     ->  GC9A01 SPI panel
Touch -> CST816D I2C driver  ->  LVGL indev (or raw coords)
Knob  -> GPIO encoder ISR/poll -> app or LVGL encoder indev
```

| Layer | Role |
|-------|------|
| **LVGL** | Widget toolkit (buttons, arcs, labels, screens). Factory firmware references LVGL buffers. |
| **LovyanGFX** (wiki sample) | Panel/bus config: `lgfx::Panel_GC9A01` + SPI pins; can also draw without LVGL |
| **Arduino_GFX** | Alternative pixel/driver path used in some 1.28" tutorials |
| **Raw SPI** | Possible but reinventing init + rotation + color; avoid |

So: **widgets by default (LVGL), pixels available underneath.** You are not stuck
at `setPixel`; you also are not forced into a closed Elecrow IDE.

## Touch

- Controller: **CST816D** (capacitive) on I2C (SDA=6, SCL=7, INT=5, RST=13).
- Delivers touch coordinates in the same 240x240 space.
- Wire into LVGL as a pointer input device, or read gestures in application code.

## Rotary encoder

Hardware knob (A=45, B=42, SW=41) is separate from touch. Use as volume/scroll
input; LVGL can treat it as an encoder indev if desired.

## On-device documentation

None beyond the running demo binary. Authoritative materials:

- Elecrow wiki (LGFX class, pin table, product claims): https://elecrow.com/wiki/CrowPanel_1.28inch-HMI_ESP32_Rotary_Display.html
- Maker Guides getting-started (Arduino, libraries, first sketch): https://www.makerguides.com/getting-started-crowpanel-1-28inch-hmi-esp32-rotary-display/
- Product page comparison table (driver ICs per size): https://www.elecrow.com/crowpanel-1-28inch-hmi-esp32-rotary-display-240-240-ips-round-touch-knob-screen.html

Wiki "Resource / github" section is thin; expect sample ZIPs on the product page
and community mirrors rather than a polished monorepo.

## Sibling sizes (do not mix drivers)

| Size | Resolution | Panel class in practice |
|------|------------|-------------------------|
| 1.28" (this board) | 240x240 | GC9A01 |
| 1.46" | 360x360 | JD9855 marketed; LovyanGFX `Panel_ST77961` in working demos |
| 2.1" | 480x480 | ST7701S |

Firmware and pin maps are **not** drop-in across sizes.

## Practical UI advice for a Volumio remote

- Use LVGL for volume arc, play/pause affordances, and status text.
- Map encoder to volume; map touch to buttons / scrub if needed.
- Keep frames light: factory image already logs LVGL buffer allocation failures
  under memory pressure -- size buffers for 240x240 carefully and prefer partial
  refresh where possible.
