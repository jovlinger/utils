# Retired: uimk2 paint path (not built)

These files are the old Core-B `uimk2_host` / zlist glass owner and its
on-device bench probe. They are NOT compiled: PlatformIO only builds `src/`,
and `include/` no longer carries these headers. Draw (`spinme/host`, symlinked
under `src/ta_host/`) is the sole glass owner since sha:87a6bf1.

They depend on `spinme/uimk2/*.h` (`uimk2_zlist`, `uimk2_event`,
`uimk2_blit`), which is likewise not on the firmware include path.

Kept on disk for reference only (placements were salvaged into
`ta_follow_chrome` / `ta_glass_device`). Deleting this directory awaits an
explicit user OK; nothing in the product links against it.
