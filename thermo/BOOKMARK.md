# Thermo bookmark

Short-term state for active work. Read this at session start. Long backlog lives in
[`TODO.md`](TODO.md); stable reference in per-tree `README.md` files.

## Active: ESP32-S3 onboard

Detail: [`onboard/hardware/esp32s3/BOOKMARK.md`](onboard/hardware/esp32s3/BOOKMARK.md).

Host-testable Rust (`protocol`, `auth`, `ir`, `app_core`, contract tests) is in tree;
`make -C thermo/onboard/hardware/esp32s3 test` passes. No ESP-IDF firmware loop or
flash deploy yet. HAT `.vox` files have base placement only.

## Pico2W HAT (idle)

Detail: [`onboard/hardware/pico2w/hat/BOOKMARK.md`](onboard/hardware/pico2w/hat/BOOKMARK.md).

`up-side.vox` has trace routing but fails `voxtool.py check` (row-count mismatch) and
has an open `3V3` rail FIXME.
