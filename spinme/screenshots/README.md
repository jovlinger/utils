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
# (cwd: spinme/host; sources in tests/)
```

| File | Screen |
|------|--------|
| `main_mpd.png` | Main / default quiet glass (`spinme` + clock) |
| `main_playing.png` | Main with sample artist/album/title + playing |
| `selecting_overlay.png` | Selecting mode (down arrow + 100x100 ring) |
| `kv_view.png` | KV page still |
| `kv_edit.png` | KV edit still |

## Timed XY veil stills (`xy_timed/`)

Produced by `spinme/host/tests/local/test_xy_timed_redraw.c` (bit-identical goldens):

```bash
cd spinme/host
make build/test_xy_timed_redraw && ./build/test_xy_timed_redraw
# refresh goldens:
REGEN_XY_TIMED=1 ./build/test_xy_timed_redraw
```

Static under-veil overlapping `4`+`k`; timed under-veil digit `0..9` with
over-veil letter `a..j` overlapping that digit; z=3 veil pack66 from
RGBA `0x08080801` (`a2=1`).
