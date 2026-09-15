# USB / chip enumeration (2026-09-07)

Live probe of the board attached as `/dev/cu.usbmodem1101` on the Mac host.
No BOOTSEL reconnect was required; the device was already enumerated.

## USB

| Field | Value |
|-------|-------|
| Product | USB JTAG/serial debug unit |
| Manufacturer | Espressif |
| Vendor ID | `0x303a` |
| Product ID | `0x1001` |
| Serial (USB) | `1C:DB:D4:B3:6C:FC` |
| Device node | `/dev/cu.usbmodem1101` |
| Location ID | `0x00110000` |

Source: `system_profiler SPUSBDataType` and `ioreg -p IOUSB -l`.

Native Espressif USB-Serial/JTAG (not CP210x/CH340). Typical of ESP32-S3 boards that expose the SoC USB PHY.

## esptool flash-id / chip-id

| Field | Value |
|-------|-------|
| Chip | ESP32-S3 (QFN56), revision v0.2 |
| Features | Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240 MHz, Embedded PSRAM 8 MB (AP_3v3) |
| Crystal | 40 MHz |
| USB mode | USB-Serial/JTAG |
| MAC | `1c:db:d4:b3:6c:fc` |
| Flash manufacturer | `c8` |
| Flash device | `4018` |
| Detected flash size | 16 MB |
| eFuse flash type | quad (4 data lines) |
| eFuse flash voltage | 3.3 V |

Tool: `esptool` v5.4.0 via a throwaway `spinme/.venv-tools` (not committed).

## Serial banner (115200)

After hard reset from esptool, idle serial showed ESP-IDF core-dump messages:

```text
E (525) esp_core_dump_flash: No core dump partition found!
```

No MicroPython / CircuitPython REPL on Ctrl-C. Firmware in flash is ESP-IDF-based (or Arduino-on-IDF), not a stock MicroPython image.

## Implications for SKU matching

Must match at least:

- ESP32-S3 with **8 MB embedded PSRAM** (S3R8 / AP_3v3 class)
- **16 MB** external flash
- Native USB Serial/JTAG
- Physical product: ELECROW-family board with circular-looking touch display (per operator); prior `spinme/README.md` Waveshare identification is provisional until catalog match

Next: map these constraints to an ELECROW product page / wiki.
