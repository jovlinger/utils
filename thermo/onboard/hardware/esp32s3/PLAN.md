# ESP32-S3 HAT Plan

## Board Target

Target the ESP32-S3 dev-kit family marked `S3-N16R8` on the module and sold as
an ESP32-S3 dev kit. `N16R8` identifies the flash/PSRAM module variant more than
the carrier geometry, so the layout should follow the DevKitC-compatible header
grid and keep the board outline as a profile field.

Primary source geometry:

- Espressif ESP32-S3-DevKitC-1 v1.1 header docs:
  `https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html`
- Espressif mechanical DXF:
  `https://dl.espressif.com/dl/schematics/esp_idf/DXF_ESP32-S3-DevKitC-1_V1.1_20220429.dxf`
- Waveshare N16R8-family docs say their carrier is pin-compatible with
  ESP32-S3-DevKitC-1:
  `https://www.waveshare.com/wiki/ESP32-S3-DEV-KIT-N8R8`

## Measurement Check

The Pico2W pins used as a ruler validate the chosen header family:

- In-row pin spacing matches the Pico pitch, so use `2.54 mm`.
- Each ESP32-S3 row has two more pins than the Pico rows, so use `22` pins per
  side instead of `20`.
- The measured row-to-row distance is close to a DevKitC-style wide carrier.
  Use the precise Espressif center-to-center value, `25.40 mm`, for generated
  geometry. That is `10` pitch intervals center-to-center; an inner-edge visual
  estimate reads closer to `9` pitch intervals.

## Layout Facts

| Fact | Value |
| --- | --- |
| Hardware directory | `thermo/onboard/hardware/esp32s3/` |
| Unit pitch | `2.54 mm` |
| Header rows | `2` |
| Pins per row | `22` |
| Header center spacing | `25.40 mm` |
| Header center spacing in grid intervals | `10` |
| Initial `.vox` width | `13` columns including border columns |
| Initial `.vox` height | `24` rows including north/south border rows |
| Official Espressif outline | about `62.74 mm x 27.94 mm` |
| Waveshare N16R8-family outline | about `63.3 mm x 25.4 mm` |

The initial `up-side.vox` captures only the header grid. It intentionally has no
sensor/module pads and no routed copper yet.

## Pin Rows

Rows are north to south, pairing J1 and J3 pin numbers from the Espressif
DevKitC-1 header tables:

| Row | J1 | J3 |
| --- | --- | --- |
| 1 | `3V3` | `GND` |
| 2 | `3V3` | `GPIO43` / `TX` |
| 3 | `RST` | `GPIO44` / `RX` |
| 4 | `GPIO4` | `GPIO1` |
| 5 | `GPIO5` | `GPIO2` |
| 6 | `GPIO6` | `GPIO42` |
| 7 | `GPIO7` | `GPIO41` |
| 8 | `GPIO15` | `GPIO40` |
| 9 | `GPIO16` | `GPIO39` |
| 10 | `GPIO17` | `GPIO38` |
| 11 | `GPIO18` | `GPIO37` |
| 12 | `GPIO8` | `GPIO36` |
| 13 | `GPIO3` | `GPIO35` |
| 14 | `GPIO46` | `GPIO0` |
| 15 | `GPIO9` | `GPIO45` |
| 16 | `GPIO10` | `GPIO48` |
| 17 | `GPIO11` | `GPIO47` |
| 18 | `GPIO12` | `GPIO21` |
| 19 | `GPIO13` | `GPIO20` |
| 20 | `GPIO14` | `GPIO19` |
| 21 | `5V` | `GND` |
| 22 | `GND` | `GND` |

## Next Steps

1. Confirm the printed board against the physical ESP32-S3 module before adding
   sensor or IR module pads.
2. Keep `UNIT_MM=2.54` in `.vox` files.
3. Keep the first routed pass small: power and ground anchors first, then one
   sensor or IR module at a time.
