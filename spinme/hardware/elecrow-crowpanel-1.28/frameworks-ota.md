# Firmware frameworks and OTA

Board: CrowPanel 1.28" rotary (SKU DHE38128D). See `hardware-identity.md` in this directory.

## What is on the device now

| Observation | Implication |
|-------------|-------------|
| Strings `arduino-lib-builder`, `arduino_events` | Factory app is Arduino-on-ESP32 (IDF under the hood) |
| `ESP32S3_1.28_BLE_Server`, WiFi config strings | Demo BLE/WiFi HMI firmware |
| LVGL buffer error strings | UI path uses LVGL |
| Partition table: single `app0` ~15.9 MB at `0x10000` | **No OTA slots** on the factory layout (`nvs`, `phy_init`, `app0` only) |

Serial after reset shows ESP-IDF core-dump messages, not a MicroPython REPL.

## Vendor-claimed stacks

Elecrow wiki lists: Arduino IDE, ESP-IDF, Lua RTOS, Home Assistant / PlatformIO /
MicroPython, LVGL.

For spinme (wireless Volumio remote + optional UI), rank by OTA maturity and
board support:

| Rank | Stack | OTA story | Fit for this board |
|------|-------|-----------|--------------------|
| 1 | **Arduino + PlatformIO** (or Arduino IDE) | `ArduinoOTA` / HTTPUpdate; needs custom partition CSV with `ota_0`/`ota_1`/`otadata` (factory image lacks these) | First-class: Elecrow demos, LovyanGFX/Arduino_GFX + LVGL examples, makerguides tutorials |
| 2 | **ESP-IDF** | Native `esp_ota_*` APIs; same dual-slot partition requirement | Strong OTA; more work to port CrowPanel pin/LVGL glue than Arduino demos |
| 3 | **ESPHome / Home Assistant** | Built-in OTA over WiFi | Fine if the remote is HA-centric; weaker fit for raw Volumio HTTP client UX |
| 4 | **MicroPython** | `ota` / `mip` / custom HTTP rewrite of firmware; less polished dual-bank story than IDF | Supported in marketing copy; **not** the factory default; display+touch+encoder glue is thinner than Arduino/LVGL demos |
| 5 | Lua RTOS | Possible but niche | Ignore unless a specific need appears |

**MicroPython is not the default.** Default practical path is Arduino/PlatformIO
(matching factory + docs), with ESP-IDF if we want the cleanest OTA partition
story and long-term structure.

## OTA requirements (any C/C++ stack)

1. Replace the single-`app0` table with at least `ota_0`, `ota_1`, and `otadata`
   (plus `nvs`). 16 MB flash has room for two multi-MB app slots.
2. Ship an update channel (HTTP(S) pull, ArduinoOTA LAN push, or signed URL).
3. Pause or freeze LVGL drawing while writing flash if the UI is active (flash
   contention causes glitches on display-heavy CrowPanels; community IDF starters
   stop rendering during OTA).

## Recommendation for spinme (provisional)

- Develop and flash over USB with **PlatformIO + Arduino** framework initially
  (fastest path to encoder + touch + LVGL).
- Introduce an **OTA-ready partition table** from the first custom firmware, even
  if the first OTA endpoint comes later.
- Revisit ESP-IDF only if Arduino OTA or memory layout becomes painful.
- Keep MicroPython as a fallback experiment, not the primary plan.

## References

- Elecrow wiki (platforms): https://elecrow.com/wiki/CrowPanel_1.28inch-HMI_ESP32_Rotary_Display.html
- ESP-IDF OTA: https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-reference/system/ota.html
- Example CrowPanel IDF starter with OTA notes (7" sibling, same lessons): https://github.com/shindakun/crowpanel_7in_esp32-s3_starter
