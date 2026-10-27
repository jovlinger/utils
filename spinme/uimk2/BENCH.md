# uimk2 bench

Host: `make -C spinme/uimk2 bench-ui` (N=100, per-op warmup 8, -O2, no sanitize).

Device: the Waveshare firmware boot probe `bench_probe_short_title` times the
same `short_title_noscroll` / `update_render_draw` scene (solid RGBA, no px
bitmaps). Clock is `esp_timer_get_time`. Frames are the PSRAM pair. Each
sample zeros both frames and clears busy before the timed call. Per-op warmup
is 8. The host's 4000-call global warmup is not repeated on device.

Serial line:

    BENCH update_render_draw scene=short_title_noscroll n=100 mean_us=... stdev_us=... min_us=... max_us=... warmup=8 clock=esp_timer_get_time

## 2026-10-27

- mac mean_us: 20.23 (re-run on this tree; stdev_us 1.56). Prior note for sha:bafe588 was about 18.61.
- device mean_us: 17954.36 (stdev_us 9.05, min_us 17938, max_us 17965, n=100)
- slowdown: 17954.36 / 20.23 = 887.51
