# Thermo Onboard

Layout:

- `common/` -- shared Python (twoway, deployment metadata, heatpump IR).
- `hardware/pizero2w/` -- Pi Zero 2 W Docker images and compose deploy.
- `hardware/pico2w/` -- Pico2W Rust firmware.
- `hardware/esp32s3/` -- ESP32-S3 Rust firmware (host-testable; ESP-IDF bring-up in progress).
- `zones/<zone>/` -- per-room `zone.env` and Makefile (`kitchen`, `office`, `bedroom`).
- `install/` -- deploy dispatcher used by zone Makefiles.

## Daikin IR codes

Kitchen Daikin frames are encoded/decoded by
[`common/heatpumpirctl/`](common/heatpumpirctl/) (notably
[`ARC452A9.py`](common/heatpumpirctl/ARC452A9.py)). The reverse-engineering
write-up is [`../../public/daikin-arc452a9-ir-protocol.md`](../../public/daikin-arc452a9-ir-protocol.md).
Neither the library nor the write-up has been exported to `johaneo` yet; both
still live in this utils tree.

Make targets, zone deploy chain, and backend flags: [`AGENTS.md`](AGENTS.md).

Room examples: kitchen (Pi Zero 2 W), office (Pico2W + Midea), bedroom (Pico2W + Haier).

Pico2W: [`hardware/pico2w/README.md`](hardware/pico2w/README.md) (agent bring-up:
[`hardware/pico2w/AGENTS.md`](hardware/pico2w/AGENTS.md)).

Pi Zero 2 W: [`hardware/pizero2w/README.md`](hardware/pizero2w/README.md).

ESP32-S3: [`hardware/esp32s3/README.md`](hardware/esp32s3/README.md) (bookmark:
[`hardware/esp32s3/BOOKMARK.md`](hardware/esp32s3/BOOKMARK.md)).

Committed room templates: [`../config/`](../config/README.md). Canonical deploy
envs live in `zones/<zone>/zone.env`.
