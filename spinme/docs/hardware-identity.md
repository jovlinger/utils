# Hardware identity

**Verdict (2026-09-07):** Elecrow **CrowPanel 1.28inch-HMI ESP32 Rotary Display**
(marketing: 240x240 IPS round touch knob screen). **SKU: DHE38128D**.

Prior `README.md` Waveshare ESP32-S3-Knob-Touch-LCD-1.8 notes are **wrong for this
attached unit** and should be treated as obsolete for spinme hardware planning.

## Evidence chain

1. USB: Espressif `0x303a:0x1001` USB JTAG/serial, MAC `1c:db:d4:b3:6c:fc`
   (`docs/usb-enumerate-2026-09-07.md`).
2. esptool: ESP32-S3 (QFN56) rev v0.2, **8 MB embedded PSRAM**, **16 MB** flash.
3. On-flash ASCII strings in the running image:
   - `ELECROW`
   - `ESP32S3_1.28_BLE_Server`
   - `Failed to allocate for LVGL buf!`
   - Arduino runtime markers (`arduino-lib-builder`, `arduino_events`)
4. Catalog match: Elecrow CrowPanel rotary family shares MCU/memory across sizes;
   only the **1.28"** SKU uses firmware naming `ESP32S3_1.28_*` and GC9A01 @ 240x240.

| Candidate | SKU | Resolution | Display IC | Ruled out? |
|-----------|-----|------------|------------|------------|
| CrowPanel 1.28" rotary | DHE38128D | 240x240 | GC9A01 | **Match** (flash string) |
| CrowPanel 1.46" rotary | DHR55146D | 360x360 | JD9855 / ST77961 | No `1.46` string; different panel |
| CrowPanel 2.1" rotary | DHE03921D | 480x480 | ST7701S | No `2.1` string; different panel |
| Waveshare Knob-Touch-LCD-1.8 | (Waveshare) | 360x360 | ST77916 | No Waveshare strings; dual-MCU story does not match USB |

## Board summary

| Item | Value |
|------|-------|
| Vendor | Elecrow |
| Product | CrowPanel 1.28inch-HMI ESP32 Rotary Display |
| SKU | DHE38128D |
| MCU | ESP32-S3R8 (Xtensa LX7 dual-core, up to 240 MHz) |
| PSRAM / Flash | 8 MB / 16 MB |
| Display | 1.28" round IPS, **square framebuffer 240x240**, GC9A01 over SPI |
| Touch | Capacitive CST816D over I2C |
| Extra UI | Rotary encoder + press, WS2812 ambient LEDs (5), optional tiny OLED in demos |
| USB | Type-C / 5V; native USB-Serial/JTAG for flash+monitor |
| Buttons | RESET, BOOT |

## Vendor docs (primary)

- Product: https://www.elecrow.com/crowpanel-1-28inch-hmi-esp32-rotary-display-240-240-ips-round-touch-knob-screen.html
- Wiki: https://elecrow.com/wiki/CrowPanel_1.28inch-HMI_ESP32_Rotary_Display.html
- Community walkthrough: https://www.makerguides.com/getting-started-crowpanel-1-28inch-hmi-esp32-rotary-display/

Wiki claims support for Arduino IDE, ESP-IDF, Lua RTOS, Home Assistant /
PlatformIO / MicroPython, and LVGL. Factory image on this unit is **Arduino +
LVGL**, not MicroPython (see `docs/frameworks-ota.md`, `docs/display-touch.md`).

## On-device "docs"

There is no readable documentation partition. The device carries a single large
`app0` firmware image with Elecrow demo strings. Schematics, pin maps, and demo
source live on the **wiki / product downloads**, not on the flash.

## Pin map (from Elecrow wiki demo)

- Display GC9A01 SPI: SCLK=10, MOSI=11, DC=3, CS=9, RST=14; backlight=46
- Touch CST816D I2C: SDA=6, SCL=7, INT=5, RST=13
- Encoder: A=45, B=42, SW=41
- WS2812: pin 48, count 5
