# Firmware frameworks and OTA -- Waveshare Knob-Touch-LCD-1.8

See `hardware-identity.md` and `usb-enumerate-2026-09-07.md`.

## Live probe (2026-09-07)

### U4WDH orientation

| Observation | Implication |
|-------------|-------------|
| ESP32-U4WDH + CH340 | Classic BT / audio half |
| `TAIJI_KNOB_*`, IDF paths | ESP-IDF knob firmware |
| `factory` + `storage` only | No OTA on 4 MB image |

### S3 orientation (device-end flip)

| Observation | Implication |
|-------------|-------------|
| ESP32-S3, 8 MB PSRAM, 16 MB flash, native USB JTAG | Same memory class as CrowPanel |
| `arduino-lib-builder`, PlatformIO Windows build paths | **Arduino + PlatformIO** factory HMI |
| `esp_lcd_st77916`, `CST816S`, LVGL task | Display/touch/UI stack confirmed in flash |
| Partitions `app0`/`app1`/`otadata` | **OTA-ready** already (unlike CrowPanel factory) |
| Captive WiFi HTML + boot tasks (DAC/haptic/SD) | Full demo firmware, not a blank board |

## Ranked stacks (board family)

Same recommendation shape as CrowPanel, with dual-MCU caveat:

| Rank | Stack | Notes |
|------|-------|-------|
| 1 | **Arduino + PlatformIO** on **ESP32-S3** | Matches Waveshare wiki demos for LCD/encoder; flip USB to S3 |
| 2 | **ESP-IDF** on S3 | Strong OTA; U4WDH side already looks IDF-native |
| 3 | ESPHome | Possible; HA-centric |
| 4 | MicroPython | Possible; thinner display glue than Arduino demos |
| -- | U4WDH-only Arduino/IDF | Use only for Classic BT / audio roles |

**Do not** treat U4WDH and S3 as one flash target. Orientation selects which chip
esptool sees.

## OTA

Either MCU needs an explicit dual-app partition table for OTA. Current U4WDH
image is single `factory` (~1.6 MB app) + SPIFFS-like `storage` on 4 MB flash --
OTA room is tight on the U4WDH; the S3 side (typically 16 MB) is the realistic
OTA host for a Volumio remote UI.
