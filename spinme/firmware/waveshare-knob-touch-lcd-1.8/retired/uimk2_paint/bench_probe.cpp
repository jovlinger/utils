#include "bench_probe.h"

#include <Arduino.h>
#include <esp_timer.h>
#include <string.h>

extern "C" {
#include "uimk2_blit.h"
#include "uimk2_host.h"
}

/* Same scene and sample count as spinme/uimk2/bench_ui.c
 * short_title_noscroll / update_render_draw. Per-op warmup matches
 * BENCH_WARMUP there. The host also discards a long global warmup for
 * the Mac clock; this probe does not. Each sample zeros both frames
 * and clears busy before the timed call, matching reset_frame. Text
 * is stored the same way and is not painted (px is NULL). */

static const int kBenchN = 100;
static const int kBenchWarmup = 8;
static const int kTitle = 2;

static volatile uint32_t gBenchSink;
static uimk2_zlist gBenchZ;
static uimk2_ring gBenchRing;
static int gPings;

static uint64_t isqrt_u64(uint64_t n) {
  uint64_t x;
  uint64_t y;
  if (n == 0ull) {
    return 0ull;
  }
  x = n;
  y = (x + 1ull) / 2ull;
  while (y < x) {
    x = y;
    y = (x + n / x) / 2ull;
  }
  return x;
}

static void set_text(uimk2_shape *s, const char *text) {
  size_t n = strlen(text);
  if (n >= (size_t)UIMK2_ZLIST_TEXT) {
    n = (size_t)UIMK2_ZLIST_TEXT - 1u;
  }
  memset(s->text, 0, sizeof s->text);
  memcpy(s->text, text, n);
}

static uimk2_shape_desc box(uint8_t sel, int x, int y, int w, int h, int r,
                            int g, int b, int a) {
  uimk2_shape_desc d;
  memset(&d, 0, sizeof d);
  d.update_selector = sel;
  d.x = (int16_t)x;
  d.y = (int16_t)y;
  d.w = (uint16_t)w;
  d.h = (uint16_t)h;
  d.rgba[0] = (uint8_t)r;
  d.rgba[1] = (uint8_t)g;
  d.rgba[2] = (uint8_t)b;
  d.rgba[3] = (uint8_t)a;
  return d;
}

static void on_ping(void *ctx) {
  int *n = static_cast<int *>(ctx);
  (*n)++;
}

static bool build_short(uint8_t *curr, uint8_t *next) {
  uimk2_shape_desc d[4];
  memset(d, 0, sizeof d);
  d[0] = box(UIMK2_UPD_FIXED, 16, 188, 100, 36, 40, 160, 70, 255);
  d[0].is_transport = true;
  d[0].accept_hit = true;
  d[1] = box(UIMK2_UPD_FIXED, 16, 260, 72, 36, 180, 180, 200, 255);
  d[2] = box(UIMK2_UPD_FIXED, 16, 36, 300, 28, 230, 230, 230, 255);
  d[2].step_x = 0;
  d[3] = box(UIMK2_UPD_FIXED, 0, 0, (int)PANEL_W, (int)PANEL_H, 18, 18, 22, 255);
  d[3].is_base = true;
  uimk2_ring_init(&gBenchRing);
  gPings = 0;
  if (!uimk2_zlist_build(&gBenchZ, d, 4, curr, next, &gBenchRing, on_ping,
                         &gPings)) {
    return false;
  }
  set_text(&gBenchZ.shape[0], "play");
  set_text(&gBenchZ.shape[1], "40");
  set_text(&gBenchZ.shape[kTitle], "Song");
  return true;
}

static void reset_frame(uint8_t *curr, uint8_t *next) {
  const size_t bytes = (size_t)UIMK2_FRAME_BYTES;
  gBenchZ.curr = curr;
  gBenchZ.next = next;
  memset(curr, 0, bytes);
  memset(next, 0, bytes);
  uimk2_ring_init(&gBenchRing);
  gBenchZ.busy = false;
  gBenchZ.redraw_attempt = 0;
  gBenchZ.redraw_held = false;
  gBenchZ.hold_redraw = false;
  gBenchZ.shape[kTitle].ox = 0;
  gBenchZ.shape[kTitle].oy = 0;
}

static void wait_serial(void) {
  const uint32_t start = millis();
  while (!Serial && (millis() - start) < 3000u) {
    delay(10);
  }
}

/* mean_fp and stdev are in 0.01 us. Samples are whole microseconds. */
static void print_bench(const int64_t *samples) {
  int64_t sum = 0;
  int64_t min_us = samples[0];
  int64_t max_us = samples[0];
  int64_t mean_fp;
  uint64_t acc = 0;
  uint64_t stdev_fp;
  int i;
  for (i = 0; i < kBenchN; ++i) {
    sum += samples[i];
    if (samples[i] < min_us) {
      min_us = samples[i];
    }
    if (samples[i] > max_us) {
      max_us = samples[i];
    }
  }
  mean_fp = (sum * 100) / kBenchN;
  for (i = 0; i < kBenchN; ++i) {
    int64_t diff = samples[i] * 100 - mean_fp;
    uint64_t ad = diff < 0 ? (uint64_t)(-diff) : (uint64_t)diff;
    uint64_t sq;
    if (ad > 0xffffffffull) {
      acc = UINT64_MAX;
      break;
    }
    sq = ad * ad;
    if (acc > UINT64_MAX - sq) {
      acc = UINT64_MAX;
      break;
    }
    acc += sq;
  }
  if (acc != UINT64_MAX) {
    acc /= (uint64_t)(kBenchN - 1);
  }
  stdev_fp = isqrt_u64(acc);
  Serial.printf(
      "BENCH update_render_draw scene=short_title_noscroll n=%d "
      "mean_us=%u.%02u stdev_us=%u.%02u min_us=%u max_us=%u "
      "warmup=%d clock=esp_timer_get_time\n",
      kBenchN, (unsigned)(mean_fp / 100), (unsigned)(mean_fp % 100),
      (unsigned)(stdev_fp / 100), (unsigned)(stdev_fp % 100),
      (unsigned)min_us, (unsigned)max_us, kBenchWarmup);
  Serial.flush();
}

bool bench_probe_short_title(uint8_t *curr, uint8_t *next) {
  int64_t samples[kBenchN];
  int i;
  wait_serial();
  if (curr == nullptr || next == nullptr) {
    Serial.println("BENCH update_render_draw scene=short_title_noscroll error=buffers");
    Serial.flush();
    return false;
  }
  if (!build_short(curr, next)) {
    Serial.println("BENCH update_render_draw scene=short_title_noscroll error=build");
    Serial.flush();
    return false;
  }
  Serial.println("bench probe start short_title_noscroll");
  Serial.flush();
  for (i = 0; i < kBenchWarmup; ++i) {
    reset_frame(curr, next);
    uimk2_zlist_update_render_draw(&gBenchZ);
    gBenchSink += gBenchZ.row_dirty[0];
  }
  for (i = 0; i < kBenchN; ++i) {
    int64_t t0;
    int64_t t1;
    reset_frame(curr, next);
    t0 = esp_timer_get_time();
    asm volatile("" ::: "memory");
    uimk2_zlist_update_render_draw(&gBenchZ);
    asm volatile("" ::: "memory");
    t1 = esp_timer_get_time();
    samples[i] = t1 - t0;
    if (samples[i] < 0) {
      samples[i] = 0;
    }
    gBenchSink += gBenchZ.row_dirty[0];
    gBenchSink += (uint32_t)(uint16_t)gBenchZ.shape[kTitle].ox;
  }
  print_bench(samples);
  (void)gBenchSink;
  return true;
}

static void fill_blit_dense(uint8_t *src) {
  const uint32_t n = (uint32_t)PANEL_W * (uint32_t)PANEL_H;
  uint32_t i;
  for (i = 0; i < n; ++i) {
    src[i * 4u + 0u] = (uint8_t)((i * 3u) & 255u);
    src[i * 4u + 1u] = (uint8_t)((i * 5u) & 255u);
    src[i * 4u + 2u] = (uint8_t)((i * 7u) & 255u);
    src[i * 4u + 3u] = (uint8_t)((i * 11u) & 255u);
  }
}

static void fill_blit_sparse(uint8_t *src) {
  const uint32_t w = (uint32_t)PANEL_W;
  const uint32_t h = (uint32_t)PANEL_H;
  uint32_t y;
  uint32_t x;
  memset(src, 0, (size_t)UIMK2_FRAME_BYTES);
  for (y = 0; y < h; ++y) {
    for (x = 0; x < w; ++x) {
      uint32_t i = y * w + x;
      if ((x % 12u) == 3u || (x % 12u) == 4u) {
        src[i * 4u + 0u] = 200;
        src[i * 4u + 1u] = 100;
        src[i * 4u + 2u] = 50;
        src[i * 4u + 3u] = 255;
      }
    }
  }
}

static void pack_blit_rows(uint32_t *dst, const uint8_t *rgba) {
  uint32_t y;
  for (y = 0; y < (uint32_t)PANEL_H; ++y) {
    uimk2_blit_rgba_row_to_pack66(dst + y * (uint32_t)PANEL_W,
                                  rgba + y * (uint32_t)PANEL_W * 4u,
                                  (uint32_t)PANEL_W);
  }
}

static void print_blit_named(const char *tag, uint32_t tw, int correct,
                             const int64_t *samples) {
  int64_t sum = 0;
  int64_t min_us = samples[0];
  int64_t max_us = samples[0];
  int64_t mean_fp;
  uint64_t acc = 0;
  uint64_t stdev_fp;
  unsigned cv_fp = 0;
  int i;
  for (i = 0; i < kBenchN; ++i) {
    sum += samples[i];
    if (samples[i] < min_us) {
      min_us = samples[i];
    }
    if (samples[i] > max_us) {
      max_us = samples[i];
    }
  }
  mean_fp = (sum * 100) / kBenchN;
  for (i = 0; i < kBenchN; ++i) {
    int64_t diff = samples[i] * 100 - mean_fp;
    uint64_t ad = diff < 0 ? (uint64_t)(-diff) : (uint64_t)diff;
    uint64_t sq;
    if (ad > 0xffffffffull) {
      acc = UINT64_MAX;
      break;
    }
    sq = ad * ad;
    if (acc > UINT64_MAX - sq) {
      acc = UINT64_MAX;
      break;
    }
    acc += sq;
  }
  if (acc != UINT64_MAX) {
    acc /= (uint64_t)(kBenchN - 1);
  }
  stdev_fp = isqrt_u64(acc);
  if (mean_fp > 0) {
    cv_fp = (unsigned)((stdev_fp * 1000000ull) / (uint64_t)mean_fp);
  }
  Serial.printf(
      "BENCH %s tile=%ux%u correct=%d n=%d mean_us=%u.%02u stdev_us=%u.%02u "
      "cv_pct=%u.%04u min_us=%u max_us=%u warmup=%d clock=esp_timer_get_time\n",
      tag, (unsigned)tw, (unsigned)tw, correct, kBenchN,
      (unsigned)(mean_fp / 100), (unsigned)(mean_fp % 100),
      (unsigned)(stdev_fp / 100), (unsigned)(stdev_fp % 100), cv_fp / 10000,
      cv_fp % 10000, (unsigned)min_us, (unsigned)max_us, kBenchWarmup);
  Serial.flush();
}

bool bench_probe_blit(uint8_t *curr, uint8_t *next) {
  int64_t samples[kBenchN];
  const uint32_t tw = TILE_W;
  const uint32_t npix = (uint32_t)PANEL_W * (uint32_t)PANEL_H;
  /* next holds RGBA source; after pack, src66 aliases next. curr = dst. */
  uint32_t *dst66 = reinterpret_cast<uint32_t *>(curr);
  uint32_t *src66 = reinterpret_cast<uint32_t *>(next);
  int i;
  int correct;
  int pass;
  wait_serial();
  if (curr == nullptr || next == nullptr) {
    Serial.println("BENCH blit error=buffers");
    Serial.flush();
    return false;
  }
  Serial.println("bench probe start blit dense+sparse");
  Serial.flush();

  for (pass = 0; pass < 2; ++pass) {
    const char *tag8888 =
        pass == 0 ? "blit_src_over_8888_dense_clear" : "blit_src_over_8888_sparse_clear";
    const char *tag66 =
        pass == 0 ? "blit_src_over66_dense_clear" : "blit_src_over66_sparse_clear";
    if (pass == 0) {
      fill_blit_dense(next);
    } else {
      fill_blit_sparse(next);
    }

    memset(curr, 0, (size_t)UIMK2_FRAME_BYTES);
    uimk2_blit_src_over(curr, PANEL_W, next, PANEL_W, PANEL_W, PANEL_H, tw, tw);
    correct = memcmp(curr, next, (size_t)UIMK2_FRAME_BYTES) == 0 ? 1 : 0;
    if (!correct) {
      Serial.printf("BENCH %s correct=0\n", tag8888);
      Serial.flush();
      return false;
    }
    for (i = 0; i < kBenchWarmup; ++i) {
      memset(curr, 0, (size_t)UIMK2_FRAME_BYTES);
      uimk2_blit_src_over(curr, PANEL_W, next, PANEL_W, PANEL_W, PANEL_H, tw,
                          tw);
      gBenchSink += curr[0];
    }
    for (i = 0; i < kBenchN; ++i) {
      int64_t t0;
      int64_t t1;
      memset(curr, 0, (size_t)UIMK2_FRAME_BYTES);
      t0 = esp_timer_get_time();
      asm volatile("" ::: "memory");
      uimk2_blit_src_over(curr, PANEL_W, next, PANEL_W, PANEL_W, PANEL_H, tw,
                          tw);
      asm volatile("" ::: "memory");
      t1 = esp_timer_get_time();
      samples[i] = t1 - t0 < 0 ? 0 : t1 - t0;
      gBenchSink += curr[(size_t)(i & 255)];
    }
    print_blit_named(tag8888, tw, correct, samples);

    /* Pack+encode into next (overwrites RGBA). */
    {
      uint8_t *rgba_copy = curr; /* reuse cleared curr as temp RGBA */
      memcpy(rgba_copy, next, (size_t)UIMK2_FRAME_BYTES);
      pack_blit_rows(src66, rgba_copy);
    }

    memset(dst66, 0, (size_t)npix * sizeof(uint32_t));
    uimk2_blit_src_over66(dst66, PANEL_W, src66, PANEL_W, PANEL_W, PANEL_H, tw,
                          tw);
    correct = 1;
    {
      uint32_t y;
      for (y = 0; y < (uint32_t)PANEL_H && correct; ++y) {
        uint32_t x = 0;
        while (x < (uint32_t)PANEL_W) {
          uint32_t s = src66[y * (uint32_t)PANEL_W + x];
          if (uimk2_blit_is_skip66(s)) {
            uint32_t skip = uimk2_blit_skip66(s);
            uint32_t k;
            if (skip > (uint32_t)PANEL_W - x) {
              skip = (uint32_t)PANEL_W - x;
            }
            for (k = 0; k < skip; ++k) {
              if (dst66[y * (uint32_t)PANEL_W + x + k] != 0u) {
                correct = 0;
                break;
              }
            }
            x += skip;
            continue;
          }
          if (dst66[y * (uint32_t)PANEL_W + x] != s) {
            correct = 0;
            break;
          }
          x++;
        }
      }
    }
    if (!correct) {
      Serial.printf("BENCH %s correct=0\n", tag66);
      Serial.flush();
      return false;
    }
    for (i = 0; i < kBenchWarmup; ++i) {
      memset(dst66, 0, (size_t)npix * sizeof(uint32_t));
      uimk2_blit_src_over66(dst66, PANEL_W, src66, PANEL_W, PANEL_W, PANEL_H, tw,
                            tw);
      gBenchSink += dst66[0];
    }
    for (i = 0; i < kBenchN; ++i) {
      int64_t t0;
      int64_t t1;
      memset(dst66, 0, (size_t)npix * sizeof(uint32_t));
      t0 = esp_timer_get_time();
      asm volatile("" ::: "memory");
      uimk2_blit_src_over66(dst66, PANEL_W, src66, PANEL_W, PANEL_W, PANEL_H, tw,
                            tw);
      asm volatile("" ::: "memory");
      t1 = esp_timer_get_time();
      samples[i] = t1 - t0 < 0 ? 0 : t1 - t0;
      gBenchSink += dst66[(size_t)(i & 255)];
    }
    print_blit_named(tag66, tw, correct, samples);
  }

  (void)gBenchSink;
  return true;
}
