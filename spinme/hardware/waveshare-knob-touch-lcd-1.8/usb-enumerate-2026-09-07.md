# USB / chip enumeration -- Waveshare (2026-09-07)

Two Type-C orientations on the **device** end select which MCU is USB-active.
Flipping the **computer** end did not change the MCU (experiment logged earlier).

## Orientation A -- ESP32-U4WDH (pre-flip)

| Field | Value |
|-------|-------|
| USB | CH340-class `0x1a86:0x7523` |
| Device | `/dev/cu.usbserial-10` |
| Chip | ESP32-U4WDH rev v3.1 |
| MAC | `44:1d:64:92:a2:f8` |
| Flash | 4 MB |
| Firmware | ESP-IDF `TAIJI_KNOB_*` / `iot_knob` |
| Partitions | `nvs`, `phy_init`, `factory`, `storage` (no OTA) |

## Orientation B -- ESP32-S3 (after device-end flip) **current**

| Field | Value |
|-------|-------|
| USB | Espressif USB JTAG/serial `0x303a:0x1001` |
| Device | `/dev/cu.usbmodem101` |
| Serial (USB) | `20:6E:F1:A1:2C:70` |
| Chip | **ESP32-S3** (QFN56) rev v0.2 |
| Features | Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240 MHz, **Embedded PSRAM 8 MB (AP_3v3)** |
| USB mode | USB-Serial/JTAG |
| MAC | `20:6e:f1:a1:2c:70` |
| Flash | **16 MB** (mfg `68`, device `4018`, quad, 3.3 V) |

### S3 partition table (OTA-ready)

| Label | Type | Offset | Size |
|-------|------|--------|------|
| nvs | data/nvs | 0x9000 | 0x5000 |
| otadata | data/ota | 0xe000 | 0x2000 |
| app0 | app/ota_0 | 0x10000 | 0x300000 (3 MB) |
| app1 | app/ota_1 | 0x310000 | 0x300000 (3 MB) |
| spiffs | data/spiffs | 0x610000 | 0x9e0000 (~9.9 MB) |
| coredump | data/coredump | 0xff0000 | 0x10000 |

### S3 firmware strings / boot log

- Arduino-on-ESP32 via PlatformIO (`arduino-lib-builder`, build path
  `C:/Users/Fei/.platformio/packages/framework-arduinoespressif32...`)
- Display: `esp_lcd_st77916.c`, `Bst77916`, `ESP32_Display_Panel-0.2.2`
- Touch: `CST816S` / `CST816S_CPP`
- UI: LVGL (`Lvgl task started`, `task_lvgl`; also `LVGL disp_draw_buf_init malloc failed`)
- Knob: `iot_knob`, `Rotary konb started`, `TAIJI KNOB 32` / `HUB`
- WiFi captive portal HTML (`Configure WiFi`, `/wifilist`, `/configwifi`)
- OTA APIs present (`esp_ota_ops.c`, `otadata`)
- Boot serial (115200): System start, PSRAM used ~5.9 MB, I2C OK, TF Card SDSC 480MB,
  LVGL/IO/WIFI AP/DAC/FFT/UART1/HAPTIC/Rotary tasks, then GUI + boot mjpeg

**Not MicroPython.** Rich HMI demo (WiFi AP config, LVGL, DAC, haptic, SD).

## Contrast with Elecrow CrowPanel 1.28

| | Waveshare S3 (this orientation) | Elecrow CrowPanel 1.28 |
|--|----------------------------------|-------------------------|
| USB | Espressif `0x303a:0x1001` | Same class |
| Chip | ESP32-S3 + 8 MB PSRAM + 16 MB flash | Same class |
| Panel | ST77916 QSPI 360x360 | GC9A01 SPI 240x240 |
| Touch | CST816S | CST816D |
| Factory app | Arduino+LVGL Taiji/Viewe knob HMI; **OTA partitions present** | Arduino+LVGL; **single huge app0**, no OTA |
| Extra MCU | U4WDH on other Type-C orientation | None |

## How to select MCU

1. Plug Type-C into the **board**; orientation selects S3 vs U4WDH.
2. Confirm with `esptool --port <cu> flash-id`: want **ESP32-S3** for UI work.
3. Host-end cable flip does not switch MCUs.
