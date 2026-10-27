# uimk2 bench

Host: `make -C spinme/uimk2 bench-ui` (N=100, per-op warmup 8, -O2, no sanitize).

Device: the Waveshare firmware boot probe `bench_probe_short_title` times the
same `short_title_noscroll` / `update_render_draw` scene (solid RGBA, no px
bitmaps). Clock is `esp_timer_get_time`. Frames are the PSRAM pair. Each
sample zeros both frames and clears busy before the timed call. Per-op warmup
is 8. The host's 4000-call global warmup is not repeated on device.

Serial line:

    BENCH update_render_draw scene=short_title_noscroll n=100 mean_us=... stdev_us=... min_us=... max_us=... warmup=8 clock=esp_timer_get_time

## 2026-10-27 update_render_draw

- mac mean_us: 20.23 (re-run on this tree; stdev_us 1.56). Prior note for sha:bafe588 was about 18.61.
- device mean_us: 17954.36 (stdev_us 9.05, min_us 17938, max_us 17965, n=100)
- slowdown: 17954.36 / 20.23 = 887.51

Re-flash on blit-tile-alpha: device mean_us 17936.78 (stdev_us 6.86).

## Tiled blit_src_over (clear base, alpha 0)

Host: `make -C spinme/uimk2 bench-blit`. Device: boot `bench_probe_blit`.
Straight src-over of a full 360x360 RGBA src onto a zeroed dst; correctness
requires dst == src after the blit. Tile sizes are square; working set is
`2 * tile * tile * 4` bytes (src+dst). Default `TILE_W`/`TILE_H` is 32
(8192-byte working set) to leave headroom in a 32 KB S3 D-cache.

cv_pct = 100 * stdev / mean. The interesting compare is ESP vs M2
**variability** (cv), not the absolute M2 microseconds.

| tile | work_B | M2 mean_us | M2 cv% | ESP mean_us | ESP cv% | slowdown |
|------|--------|------------|--------|-------------|---------|----------|
| 8x8 | 512 | 354.68 | 1.67 | 64653.39 | 0.0054 | 182.3 |
| 16x16 | 2048 | 335.50 | 1.47 | 63922.14 | 0.0028 | 190.5 |
| 20x20 | 3200 | 332.55 | 3.13 | 63741.98 | 0.0064 | 191.7 |
| 24x24 | 4608 | 322.16 | 1.81 | 63616.96 | 0.0059 | 197.5 |
| 30x30 | 7200 | 315.60 | 0.48 | 63533.54 | 0.0066 | 201.3 |
| 32x32 | 8192 | 317.37 | 0.57 | 63523.68 | 0.0063 | 200.2 |
| 36x36 | 10368 | 317.03 | 0.52 | 63485.78 | 0.0063 | 200.3 |
| 40x40 | 12800 | 316.58 | 1.71 | 63399.53 | 0.0071 | 200.3 |
| 45x45 | 16200 | 314.56 | 1.86 | 63431.56 | 0.0084 | 201.7 |
| 60x60 | 28800 | 319.32 | 3.33 | 63402.88 | 0.0068 | 198.6 |

Takeaways:

- Blit slowdown is about **180-200x**, not the ~888x of `update_render_draw`
  (different work: per-pixel divides vs host UI scene).
- ESP run-to-run cv is ~**0.006%** (stdev a few us on a 63 ms mean). M2 cv is
  ~**0.5-3%** -- tens to hundreds of times noisier relative to its mean.
- Tile size barely moves ESP mean once above ~24; M2 likes mid tiles (~30-45)
  and gets noisier at 60 (working set near a 32 KB cache).

## Packed RGB666 + 2-bit alpha (add/shift, then >>2 & mask)

Layout per `uint32_t`: `00RRRRRR 00GGGGGG 00BBBBBB` plus 2-bit A in bits 24..25.
Mid-alpha lerp is add/shift only; divide is `>> 2` then `& 0x003F3F3F`.
Over a clear base (`da==0`) the path copies src (same as straight over empty).

| path | M2 mean_us | ESP mean_us | ESP speedup vs 8888 |
|------|------------|-------------|---------------------|
| blit_src_over_8888_clear | 332.74 | 63542.21 | 1.00x |
| blit_src_over66_clear (scalar) | 71.80 | 35509.79 | **1.79x** |
| blit_src_over66_covered (scalar) | 117.50 | 39454.25 | **1.61x** |

Host gains more (~4.6x clear) because the 8888 divides hurt the M2 less evenly
than the ESP; on device the walk+PSRAM still dominate, but dropping the
per-pixel divider still saves ~28 ms/frame on clear and ~24 ms on covered.

### PIE 128-bit + Duff (implemented)

`uimk2_blit_pie.S`: `ee.vld.128.ip` / `ee.vst.128.ip` for 4-pixel chunks;
`blit_span66` aligns, Duff-unrolls those chunks, Duff-fixups 0..3 leftovers.
Lerp stays scalar per word after the wide load.

| path | ESP mean_us | vs 8888 | vs scalar pack66 |
|------|-------------|---------|------------------|
| blit_src_over66_clear + PIE | 32797.26 | **1.94x** | 1.08x |
| blit_src_over66_covered + PIE | 36661.74 | **1.73x** | 1.08x |

### Skip-RLE (A2==0 word jumps) + encode_row_skips

Dense = historical random alpha. Sparse = text-like (~2/12 ink, long clear runs).

| path | M2 us | ESP us | vs ESP 8888 dense |
|------|-------|--------|-------------------|
| 8888 dense clear | 534 | 63523 | 1.00x |
| pack66+PIE dense (no RLE era) | 72 | 32797 | 1.94x |
| pack66+skip dense clear | 140 | 38339 | 1.66x |
| 8888 sparse clear | 129 | 37827 | 1.68x |
| pack66+skip sparse clear | 81 | **23675** | **2.68x** |

Skip-RLE loses a bit on dense (extra skip bookkeeping) and wins on sparse:
ESP sparse pack66 is **1.60x** vs sparse 8888 and **1.38x** vs the best prior dense pack66+PIE clear.
