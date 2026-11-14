#include "ta_glass_device.h"

#include <string.h>
#include <time.h>

#include <Arduino.h>
#include <esp_heap_caps.h>

#include "bg_embed.h"
#include "board_pins.h"
#include "glyph_file.h"
#include "layout_box.h"
#include "panel_io.h"
#include "ta_draw_glass.h"
#include "ta_text.h"

/* Follow placements (product salvage from follow_glass): text column at
 * x=24 from the first bezel row that still holds that x; button on top. */
static const int kTextX = 24;
static const int kTextY = 96;
static const int kGap = 4;
static const int kButtonY = 8;
static const uint16_t kViewW = 312;
static const uint16_t kHitPadX = 12;
static const uint16_t kHitPadY = 6;

/* Glyph atlas: ascii 32..126 -> shape idx 1..95 (< 128 for the clock pack). */
static ta_shape_bitmap_t gGlyph[95];
static ta_glyph_map_t gMap;
static int8_t gKern[95];
static ta_pack66_t *gBase = nullptr;
static uint8_t *gRgbaScratch = nullptr;
static bool gBound = false;

static ta_pack66_t *psram_px(size_t count) {
  void *p = heap_caps_malloc(count * sizeof(ta_pack66_t),
                             MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (p == nullptr) {
    p = malloc(count * sizeof(ta_pack66_t));
  }
  return static_cast<ta_pack66_t *>(p);
}

static void be_push(int x, int y, int w, int h, const ta_pack66_t *px,
                    int stride) {
  panel_push_pack66(x, y, w, h, px, stride);
}

static void be_backlight(int on) {
  digitalWrite(PIN_LCD_BL, on ? HIGH : LOW);
}

static int be_clock(char out[9]) {
  time_t now = time(nullptr);
  struct tm tmv;
  if (now < 1600000000) {
    return -1; /* no wall clock yet: glass falls back to uptime */
  }
  localtime_r(&now, &tmv);
  snprintf(out, 9, "%02d:%02d:%02d", tmv.tm_hour, tmv.tm_min, tmv.tm_sec);
  return 0;
}

static const ta_glass_backend_t kBackend = {psram_px, be_push, be_backlight,
                                            be_clock};

static inline uint8_t a2_of(uint8_t alpha) {
  if (alpha >= 192) {
    return 3;
  }
  if (alpha >= 128) {
    return 2;
  }
  if (alpha >= 64) {
    return 1;
  }
  return 0;
}

/* One glyph -> white pack66 bitmap in PSRAM. Space is a clear word shim. */
static bool build_glyph(int i, uint16_t *max_h) {
  const char s[2] = {(char)(32 + i), '\0'};
  LayBox box;
  const uint8_t *rgba = nullptr;
  ta_shape_bitmap_t *g = &gGlyph[i];
  int n = glyph_line_items(s, &box, &rgba, 1);
  int w;
  int h;
  memset(g, 0, sizeof(*g));
  g->tag = TA_SHAPE_TAG_BITMAP;
  if (n <= 0) {
    return true; /* unmapped: left out of the glyph map */
  }
  w = box.w > 0 ? box.w : 1;
  h = box.h > 0 ? box.h : 1;
  g->w = (uint16_t)w;
  g->h = (uint16_t)h;
  g->pixels = psram_px((size_t)w * (size_t)h);
  if (g->pixels == nullptr) {
    return false;
  }
  if (rgba == nullptr) {
    /* Shim (space): transparent run of the word gap width. */
    for (int k = 0; k < w * h; ++k) {
      g->pixels[k] = TA_PACK66_TRANSPARENT;
    }
  } else {
    for (int k = 0; k < w * h; ++k) {
      const uint8_t a = rgba[(size_t)k * 4u + 3u];
      const uint8_t a2 = a2_of(a);
      /* a2==0 must be TRANSPARENT; white+a2==0 is additive wash. */
      if (a2 == 0u) {
        g->pixels[k] = TA_PACK66_TRANSPARENT;
      } else {
        g->pixels[k] = ta_pack66_rgba(0x3f, 0x3f, 0x3f, a2);
      }
    }
  }
  if (g->h > *max_h) {
    *max_h = g->h;
  }
  return true;
}

bool ta_glass_device_bind(void) {
  uint16_t text_h = 0;
  ta_glass_cfg_t cfg;
  if (gBound) {
    return true;
  }
  if (!glyph_file_mmap()) {
    Serial.println("glass: glyph mmap fail");
    return false;
  }
  ta_glyph_map_clear(&gMap);
  for (int i = 0; i < 95; ++i) {
    if (!build_glyph(i, &text_h)) {
      Serial.println("glass: glyph alloc fail");
      return false;
    }
    if (gGlyph[i].w == 0) {
      continue;
    }
    if (ta_shape_table_set((unsigned)(1 + i), &gGlyph[i]) != 0) {
      return false;
    }
    (void)ta_glyph_map_set(&gMap, (char)(32 + i), (unsigned)(1 + i));
    gKern[i] = (int8_t)glyph_letter_hshim().w;
  }
  gKern[0] = 0; /* no letter shim after a word gap */
  if (text_h == 0) {
    text_h = (uint16_t)glyph_body_h();
  }

  /* Base: boot art from the flash embed, converted once to pack66. */
  gBase = psram_px((size_t)LCD_WIDTH * (size_t)LCD_HEIGHT);
  gRgbaScratch = static_cast<uint8_t *>(heap_caps_malloc(
      (size_t)LCD_WIDTH * (size_t)LCD_HEIGHT * 4u,
      MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (gBase == nullptr || gRgbaScratch == nullptr) {
    Serial.println("glass: base alloc fail");
    return false;
  }
  {
    const size_t want = (size_t)LCD_WIDTH * (size_t)LCD_HEIGHT * 4u;
    const size_t have =
        (size_t)(disintegration_360_rgba_end - disintegration_360_rgba_start);
    if (have >= want) {
      ta_glass_device_base_from_rgba(disintegration_360_rgba_start);
    } else {
      for (size_t k = 0; k < (size_t)LCD_WIDTH * LCD_HEIGHT; ++k) {
        gBase[k] = ta_pack66_rgba(0, 0, 0, 3);
      }
    }
  }

  memset(&cfg, 0, sizeof(cfg));
  cfg.panel_w = LCD_WIDTH;
  cfg.panel_h = LCD_HEIGHT;
  cfg.base_pixels = gBase;
  cfg.glyphs = &gMap;
  cfg.kern_table = gKern;
  cfg.text_h = text_h;
  cfg.view_w = kViewW;
  cfg.hit_pad_x = kHitPadX;
  cfg.hit_pad_y = kHitPadY;
  cfg.text_x = kTextX;
  cfg.text_y = kTextY;
  cfg.gap = kGap;
  cfg.button_y = kButtonY;
  ta_glass_set_backend(&kBackend);
  ta_glass_set_cfg(&cfg);
  gBound = true;
  Serial.printf("glass bound: glyph_h=%u view_w=%u base=%u px psram\n",
                (unsigned)text_h, (unsigned)kViewW,
                (unsigned)(LCD_WIDTH * LCD_HEIGHT));
  return true;
}

void ta_glass_device_base_from_rgba(const uint8_t *rgba) {
  if (gBase == nullptr || rgba == nullptr) {
    return;
  }
  for (size_t k = 0; k < (size_t)LCD_WIDTH * LCD_HEIGHT; ++k) {
    const uint8_t *p = rgba + k * 4u;
    /* Base is opaque glass: ignore source alpha. */
    gBase[k] = ta_pack66_rgba((uint8_t)(p[0] >> 2), (uint8_t)(p[1] >> 2),
                              (uint8_t)(p[2] >> 2), 3);
  }
}

uint8_t *ta_glass_device_rgba_scratch(void) { return gRgbaScratch; }
