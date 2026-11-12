# Glass screen stills (PNG goldens)

Pixel-perfect UI tests. Host `test_screenshots` renders the glass stack (device
`glyphs.bin` + `disintegration_360.rgba`, 360 panel, 3x nearest-neighbor PNG)
into `spinme/host/build/ui_actual/` and compares decoded RGB to the goldens
here.

```text
cd spinme/host
make build/test_screenshots && ./build/test_screenshots
```

Refresh goldens after an intentional UI change:

```text
SPINME_UI_UPDATE_GOLDEN=1 ./build/test_screenshots
```

| File | Screen |
|------|--------|
| `main_mpd.png` | Main / default quiet glass (`spinme` + clock) |
| `main_playing.png` | Main with sample artist/album/title + playing |
| `selecting_overlay.png` | Selecting mode (down arrow + 100x100 ring) |
| `kv_view.png` | KV page still |
| `kv_edit.png` | KV edit still |
