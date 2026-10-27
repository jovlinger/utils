#include "bench_probe.h"

#include <Arduino.h>
#include <esp_timer.h>
#include <string.h>

extern "C" {
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
