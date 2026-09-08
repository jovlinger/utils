# Hardware identity -- Waveshare ESP32-S3-Knob-Touch-LCD-1.8

| Field | Value |
|-------|-------|
| Vendor | Waveshare |
| Product | ESP32-S3-Knob-Touch-LCD-1.8 |
| MCU | Dual: ESP32-S3R8 + ESP32-U4WDH (Type-C orientation selects USB-active chip) |
| Display | 1.8" IPS round; square **360x360** FB; driver **ST77916** (QSPI) |
| Touch | CST816 (I2C) |
| Extra | PCM5100A DAC, DRV2605 haptic, TF/MIC/jack |

Product: https://www.waveshare.com/esp32-s3-knob-touch-lcd-1.8.htm

Wiki: https://www.waveshare.com/wiki/ESP32-S3-Knob-Touch-LCD-1.8

## Live USB evidence (2026-09-07)

Device-end Type-C flip selects MCU. **S3 orientation is the UI/remote target.**

| Orientation | USB | Chip | MAC | Flash |
|-------------|-----|------|-----|-------|
| A (pre-flip) | CH340 `0x1a86:0x7523` `/dev/cu.usbserial-10` | ESP32-U4WDH | `44:1d:64:92:a2:f8` | 4 MB |
| B (post device flip) | Espressif `0x303a:0x1001` `/dev/cu.usbmodem101` | **ESP32-S3** + 8 MB PSRAM | `20:6e:f1:a1:2c:70` | **16 MB** |

S3 factory image: Arduino/PlatformIO + LVGL + ST77916 + CST816S; OTA `app0`/`app1`
present; WiFi config portal; SD/DAC/haptic tasks in boot log.

Details: [usb-enumerate-2026-09-07.md](usb-enumerate-2026-09-07.md),
[frameworks-ota.md](frameworks-ota.md).

Full Q/A and plan notes: [README.md](README.md).

Sibling board: [../elecrow-crowpanel-1.28/](../elecrow-crowpanel-1.28/).
