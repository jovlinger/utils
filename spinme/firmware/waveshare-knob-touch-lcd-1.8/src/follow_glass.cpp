#include "follow_glass.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <esp_heap_caps.h>

#include "bg_embed.h"
#include "glyph_file.h"
#include "layout_box.h"

#include <Arduino.h>

static const int kPadX = 12;
static const int kPadY = 6;
static const int kButtonY = 8;
static const int kTextX = 24;
/* First row whose bezel chord still contains x = 24. */
static const int kTextY = 96;
static const int kGap = 4;
/* Exterior viewport width on the panel for artist/album/title/zone. */
static const int kViewW = 312;
static const int kContentMax = 1024;
static const int kItemCap = 96;
static const int kDesireAlpha = 128;

/* Boot stand-ins until the first successful poll. */
static char gZone[32] = "spinme";
static char gArtist[96] = "This is artist";
static char gAlbum[96] = "We made an album";
static char gTitle[96] = "and the song names are very very very long";

/* gW/gH = exterior (viewport). gPw/gPh = full-width L2R text map. */
static uint8_t *gPx[FOLLOW_COUNT];
static int gW[FOLLOW_COUNT];
static int gH[FOLLOW_COUNT];
static int gPw[FOLLOW_COUNT];
static int gPh[FOLLOW_COUNT];
static uimk2_zlist *gZ = nullptr;
static bool gRewindOrigins = false;
static bool gReady = false;
/* Sole panel-sized pixmap; also FOLLOW_BASE.px in the zlist. */
static uint8_t *gBg = nullptr;

static uint8_t *alloc_px(int w, int h) {
  size_t bytes;
  uint8_t *p;
  if (w < 1) {
    w = 1;
  }
  if (h < 1) {
    h = 1;
  }
  bytes = (size_t)w * (size_t)h * 4u;
  p = static_cast<uint8_t *>(
      heap_caps_malloc(bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (p == nullptr) {
    p = static_cast<uint8_t *>(malloc(bytes));
  }
  if (p != nullptr) {
    memset(p, 0, bytes);
  }
  return p;
}

static void free_px(uint8_t *p) {
  if (p != nullptr) {
    free(p);
  }
}

/* Grow or shrink the text map for index. Keeps exterior gW/gH unchanged. */
static bool ensure_map(int index, int pw, int ph) {
  if (pw < 1) {
    pw = 1;
  }
  if (ph < 1) {
    ph = 1;
  }
  if (pw > kContentMax) {
    pw = kContentMax;
  }
  if (gPx[index] != nullptr && gPw[index] == pw && gPh[index] == ph) {
    return true;
  }
  free_px(gPx[index]);
  gPx[index] = alloc_px(pw, ph);
  gPw[index] = pw;
  gPh[index] = ph;
  return gPx[index] != nullptr;
}

static void fill_px(uint8_t *dst, int w, int h, uint8_t r, uint8_t g, uint8_t b,
                    uint8_t a) {
  const int n = w * h;
  int i;
  for (i = 0; i < n; ++i) {
    dst[i * 4 + 0] = r;
    dst[i * 4 + 1] = g;
    dst[i * 4 + 2] = b;
    dst[i * 4 + 3] = a;
  }
}

static void blend_ink(uint8_t *dst, uint8_t r, uint8_t g, uint8_t b, int alpha) {
  int inv;
  if (alpha <= 0) {
    return;
  }
  if (alpha >= 255) {
    dst[0] = r;
    dst[1] = g;
    dst[2] = b;
    dst[3] = 255;
    return;
  }
  inv = 255 - alpha;
  dst[0] = (uint8_t)((r * alpha + dst[0] * inv) / 255);
  dst[1] = (uint8_t)((g * alpha + dst[1] * inv) / 255);
  dst[2] = (uint8_t)((b * alpha + dst[2] * inv) / 255);
  dst[3] = 255;
}

static void blit_glyph(uint8_t *dst, int dw, int dh, int ox, int oy, int gw,
                       int gh, const uint8_t *rgba, uint8_t r, uint8_t g,
                       uint8_t b, int scale) {
  int row;
  int col;
  for (row = 0; row < gh; ++row) {
    const int py = oy + row;
    if (py < 0 || py >= dh) {
      continue;
    }
    for (col = 0; col < gw; ++col) {
      const int px = ox + col;
      int alpha;
      if (px < 0 || px >= dw) {
        continue;
      }
      alpha = rgba[((size_t)row * (size_t)gw + (size_t)col) * 4u + 3u];
      alpha = alpha * scale / 255;
      blend_ink(dst + ((size_t)py * (size_t)dw + (size_t)px) * 4u, r, g, b,
                alpha);
    }
  }
}

static void blit_line(uint8_t *dst, int dw, int dh, int ox, int oy,
                      const char *text, uint8_t r, uint8_t g, uint8_t b,
                      int scale) {
  LayBox boxes[kItemCap];
  const uint8_t *rgba[kItemCap];
  LayAt placed[kItemCap];
  LayUnion line;
  int n;
  int i;
  if (text == nullptr || text[0] == '\0') {
    return;
  }
  n = glyph_line_items(text, boxes, rgba, kItemCap);
  if (n <= 0) {
    return;
  }
  lay_l2r(boxes, n, VAlign_bot, placed, &line);
  for (i = 0; i < n; ++i) {
    int gx;
    int gy;
    if (rgba[i] == nullptr) {
      continue;
    }
    gx = (placed[i].cx - placed[i].w / 2) - line.x + ox;
    gy = (placed[i].cy - placed[i].h / 2) - line.y + oy;
    blit_glyph(dst, dw, dh, gx, gy, placed[i].w, placed[i].h, rgba[i], r, g, b,
               scale);
  }
}

/* Full L2R ink width (clamped only by kContentMax). */
static void measure_content(const char *text, int *w, int *h) {
  int tw = 0;
  int th = 0;
  if (glyph_line_size(text, &tw, &th) == 0 || tw < 1 || th < 1) {
    tw = 8;
    th = 13;
  }
  if (tw > kContentMax) {
    tw = kContentMax;
  }
  *w = tw;
  *h = th;
}

static void measure(const char *text, int *w, int *h) {
  measure_content(text, w, h);
  if (*w > kViewW) {
    *w = kViewW;
  }
}

static void copy_cap(char *dst, size_t dst_len, const char *src) {
  size_t i = 0;
  if (dst_len == 0) {
    return;
  }
  if (src == nullptr) {
    dst[0] = '\0';
    return;
  }
  while (src[i] != '\0' && i + 1 < dst_len) {
    dst[i] = src[i];
    i++;
  }
  dst[i] = '\0';
}

void follow_glass_set_track(const char *artist, const char *album,
                            const char *title) {
  copy_cap(gArtist, sizeof gArtist, artist);
  copy_cap(gAlbum, sizeof gAlbum, album);
  copy_cap(gTitle, sizeof gTitle, title);
  gRewindOrigins = true;
}

static void clear_desc(uimk2_shape_desc *d) { memset(d, 0, sizeof *d); }

/* Exterior is the viewport; pw/ph describe the full-width text map. */
static void place_line(uimk2_shape_desc *d, int index, int x, int y, int w,
                       int h) {
  clear_desc(d);
  d->update_selector = (uint8_t)UIMK2_UPD_FIXED;
  d->x = (int16_t)x;
  d->y = (int16_t)y;
  d->w = (uint16_t)w;
  d->h = (uint16_t)h;
  d->pw = (uint16_t)gPw[index];
  d->ph = (uint16_t)gPh[index];
  d->px = gPx[index];
}

/* Paint full-width L2R into the text map. Update selector:
 * CLOCKTEXT stays CLOCKTEXT (string comes from the update switch);
 * otherwise SCROLL when the map is wider than the viewport, else FIXED.
 * Scrolling maps append three spaces so the wrap seam has a gap. */
static void paint_text_map(int index, const char *text, uint8_t r, uint8_t g,
                           uint8_t b) {
  char padded[160];
  const char *draw = text != nullptr ? text : "";
  int cw = 0;
  int ch = 0;
  uint8_t keep_sel = (uint8_t)UIMK2_UPD_FIXED;
  measure_content(draw, &cw, &ch);
  if (cw > gW[index]) {
    snprintf(padded, sizeof padded, "%s   ", draw);
    draw = padded;
    measure_content(draw, &cw, &ch);
  } else if (cw < gW[index]) {
    cw = gW[index];
  }
  if (ch < gH[index]) {
    ch = gH[index];
  }
  if (!ensure_map(index, cw, ch)) {
    return;
  }
  /* Transparent paper so the photo base shows through skip-RLE. */
  fill_px(gPx[index], gPw[index], gPh[index], 0, 0, 0, 0);
  blit_line(gPx[index], gPw[index], gPh[index], 0, 0, draw, r, g, b, 255);
  if (gZ == nullptr || index >= (int)gZ->n) {
    return;
  }
  {
    uimk2_shape *s = &gZ->shape[index];
    keep_sel = s->update_selector;
    s->px = gPx[index];
    s->pw = (uint16_t)gPw[index];
    s->ph = (uint16_t)gPh[index];
    s->w = (uint16_t)gW[index];
    s->h = (uint16_t)gH[index];
    if (keep_sel == (uint8_t)UIMK2_UPD_CLOCKTEXT) {
      s->update_selector = (uint8_t)UIMK2_UPD_CLOCKTEXT;
      s->step_x = 0;
      s->step_y = 0;
      return;
    }
    if (gRewindOrigins) {
      s->ox = 0;
      s->oy = 0;
    }
    if (gPw[index] > gW[index]) {
      s->update_selector = (uint8_t)UIMK2_UPD_SCROLL;
      s->step_x = 0;
      s->step_y = 0;
      s->dirty = true;
    } else {
      s->update_selector = (uint8_t)UIMK2_UPD_FIXED;
      s->step_x = 0;
      s->step_y = 0;
      s->ox = 0;
      s->oy = 0;
    }
  }
}

bool follow_glass_build(uimk2_zlist *z, uint8_t *curr, uint8_t *next,
                        uimk2_ring *ring, uimk2_zlist_ping_fn ping, void *ctx) {
  uimk2_shape_desc desc[FOLLOW_COUNT];
  int play_w = 0;
  int play_h = 0;
  int stop_w = 0;
  int stop_h = 0;
  int bw;
  int bh;
  int y;
  int i;
  int text_w = 0;
  int text_h = 0;
  static_assert(FOLLOW_ZONE - 1 == FOLLOW_ARTIST, "line order");
  static_assert(FOLLOW_ARTIST - 1 == FOLLOW_ALBUM, "line order");
  static_assert(FOLLOW_ALBUM - 1 == FOLLOW_TITLE, "line order");
  static_assert(FOLLOW_TITLE - 1 == FOLLOW_CLOCK, "line order");
  gReady = false;
  if (!glyph_file_mmap()) {
    return false;
  }
  measure("play", &play_w, &play_h);
  measure("stop", &stop_w, &stop_h);
  bw = (play_w > stop_w ? play_w : stop_w) + kPadX * 2;
  bh = (play_h > stop_h ? play_h : stop_h) + kPadY * 2;
  if (bw > (int)PANEL_W) {
    bw = (int)PANEL_W;
  }
  gW[FOLLOW_TRANSPORT] = bw;
  gH[FOLLOW_TRANSPORT] = bh;
  /* Exterior viewport for text lines; maps are grown to full L2R width. */
  measure("Mg", &text_w, &text_h);
  gW[FOLLOW_ZONE] = kViewW;
  gH[FOLLOW_ZONE] = text_h;
  gW[FOLLOW_ARTIST] = kViewW;
  gH[FOLLOW_ARTIST] = text_h;
  gW[FOLLOW_ALBUM] = kViewW;
  gH[FOLLOW_ALBUM] = text_h;
  gW[FOLLOW_TITLE] = kViewW;
  gH[FOLLOW_TITLE] = text_h;
  measure("88:88:88", &text_w, &text_h);
  gW[FOLLOW_CLOCK] = text_w;
  gH[FOLLOW_CLOCK] = text_h;
  measure("888", &text_w, &text_h);
  gW[FOLLOW_VOLUME] = text_w;
  gH[FOLLOW_VOLUME] = text_h;
  gW[FOLLOW_DESIRE] = text_w;
  gH[FOLLOW_DESIRE] = text_h;
  for (i = 0; i < FOLLOW_COUNT; ++i) {
    gPx[i] = nullptr;
    gPw[i] = 0;
    gPh[i] = 0;
  }
  if (!ensure_map(FOLLOW_TRANSPORT, gW[FOLLOW_TRANSPORT],
                  gH[FOLLOW_TRANSPORT]) ||
      !ensure_map(FOLLOW_DESIRE, gW[FOLLOW_DESIRE], gH[FOLLOW_DESIRE]) ||
      !ensure_map(FOLLOW_VOLUME, gW[FOLLOW_VOLUME], gH[FOLLOW_VOLUME]) ||
      !ensure_map(FOLLOW_CLOCK, gW[FOLLOW_CLOCK], gH[FOLLOW_CLOCK]) ||
      !ensure_map(FOLLOW_TITLE, gW[FOLLOW_TITLE], gH[FOLLOW_TITLE]) ||
      !ensure_map(FOLLOW_ALBUM, gW[FOLLOW_ALBUM], gH[FOLLOW_ALBUM]) ||
      !ensure_map(FOLLOW_ARTIST, gW[FOLLOW_ARTIST], gH[FOLLOW_ARTIST]) ||
      !ensure_map(FOLLOW_ZONE, gW[FOLLOW_ZONE], gH[FOLLOW_ZONE])) {
    return false;
  }

  y = kTextY;
  place_line(&desc[FOLLOW_ZONE], FOLLOW_ZONE, kTextX, y, gW[FOLLOW_ZONE],
             gH[FOLLOW_ZONE]);
  y += gH[FOLLOW_ZONE] + kGap;
  place_line(&desc[FOLLOW_ARTIST], FOLLOW_ARTIST, kTextX, y, gW[FOLLOW_ARTIST],
             gH[FOLLOW_ARTIST]);
  y += gH[FOLLOW_ARTIST] + kGap;
  place_line(&desc[FOLLOW_ALBUM], FOLLOW_ALBUM, kTextX, y, gW[FOLLOW_ALBUM],
             gH[FOLLOW_ALBUM]);
  y += gH[FOLLOW_ALBUM] + kGap;
  place_line(&desc[FOLLOW_TITLE], FOLLOW_TITLE, kTextX, y, gW[FOLLOW_TITLE],
             gH[FOLLOW_TITLE]);
  y += gH[FOLLOW_TITLE] + kGap;
  place_line(&desc[FOLLOW_VOLUME], FOLLOW_VOLUME, kTextX, y, gW[FOLLOW_VOLUME],
             gH[FOLLOW_VOLUME]);
  place_line(&desc[FOLLOW_DESIRE], FOLLOW_DESIRE, kTextX, y, gW[FOLLOW_DESIRE],
             gH[FOLLOW_DESIRE]);
  /* Clock under the transport button, left-aligned with the text column. */
  place_line(&desc[FOLLOW_CLOCK], FOLLOW_CLOCK, kTextX,
             kButtonY + gH[FOLLOW_TRANSPORT] + kGap, gW[FOLLOW_CLOCK],
             gH[FOLLOW_CLOCK]);
  /* System clock string: update switch CLOCKTEXT formats clock_tick. */
  desc[FOLLOW_CLOCK].update_selector = (uint8_t)UIMK2_UPD_CLOCKTEXT;

  clear_desc(&desc[FOLLOW_TRANSPORT]);
  desc[FOLLOW_TRANSPORT].update_selector = (uint8_t)UIMK2_UPD_FIXED;
  desc[FOLLOW_TRANSPORT].accept_hit = true;
  desc[FOLLOW_TRANSPORT].is_transport = true;
  desc[FOLLOW_TRANSPORT].x =
      (int16_t)(((int)PANEL_W - gW[FOLLOW_TRANSPORT]) / 2);
  desc[FOLLOW_TRANSPORT].y = (int16_t)kButtonY;
  desc[FOLLOW_TRANSPORT].w = (uint16_t)gW[FOLLOW_TRANSPORT];
  desc[FOLLOW_TRANSPORT].h = (uint16_t)gH[FOLLOW_TRANSPORT];
  desc[FOLLOW_TRANSPORT].px = gPx[FOLLOW_TRANSPORT];

  {
    const size_t bg_bytes =
        (size_t)PANEL_W * (size_t)PANEL_H * 4u;
    const size_t embed_bytes =
        (size_t)(disintegration_360_rgba_end - disintegration_360_rgba_start);
    if (gBg == nullptr) {
      gBg = alloc_px((int)PANEL_W, (int)PANEL_H);
    }
    if (gBg == nullptr) {
      return false;
    }
    if (embed_bytes >= bg_bytes) {
      memcpy(gBg, disintegration_360_rgba_start, bg_bytes);
    } else {
      fill_px(gBg, (int)PANEL_W, (int)PANEL_H, 0, 0, 0, 255);
    }
  }
  clear_desc(&desc[FOLLOW_BASE]);
  desc[FOLLOW_BASE].update_selector = (uint8_t)UIMK2_UPD_FIXED;
  desc[FOLLOW_BASE].is_base = true;
  desc[FOLLOW_BASE].w = (uint16_t)PANEL_W;
  desc[FOLLOW_BASE].h = (uint16_t)PANEL_H;
  desc[FOLLOW_BASE].pw = (uint16_t)PANEL_W;
  desc[FOLLOW_BASE].ph = (uint16_t)PANEL_H;
  desc[FOLLOW_BASE].px = gBg;

  /* desc[] is indexed by z-order, which matches FOLLOW_* . */
  if (!uimk2_zlist_build(z, desc, (uint16_t)FOLLOW_COUNT, curr, next, ring, ping,
                         ctx)) {
    return false;
  }
  gZ = z;
  gReady = true;
  gRewindOrigins = true;
  follow_glass_raster(0, 0, false, false);
  return true;
}

static void paint_digits(uint8_t *dst, int w, int h, int value, uint8_t r,
                         uint8_t g, uint8_t b, int scale, bool clear) {
  char text[8];
  if (clear) {
    fill_px(dst, w, h, 0, 0, 0, 0);
  }
  if (value < 0) {
    blit_line(dst, w, h, 0, 0, "---", r, g, b, scale);
    return;
  }
  if (value > 999) {
    value = 999;
  }
  text[0] = (char)('0' + (value / 100) % 10);
  text[1] = (char)('0' + (value / 10) % 10);
  text[2] = (char)('0' + value % 10);
  text[3] = '\0';
  blit_line(dst, w, h, 0, 0, text, r, g, b, scale);
}

void follow_glass_raster(int polled, int desired, bool playing,
                         bool desired_on) {
  const char *label = playing ? "stop" : "play";
  const char *clock_s = "00:00:00";
  int tw = 0;
  int th = 0;
  int ox;
  int oy;
  if (!gReady) {
    return;
  }
  paint_text_map(FOLLOW_ZONE, gZone, 255, 255, 0);
  paint_text_map(FOLLOW_ARTIST, gArtist, 255, 255, 255);
  paint_text_map(FOLLOW_ALBUM, gAlbum, 255, 255, 255);
  paint_text_map(FOLLOW_TITLE, gTitle, 255, 255, 255);
  gRewindOrigins = false;

  /* Pixels only: CLOCKTEXT already wrote shape.text in update(). */
  if (gZ != nullptr && FOLLOW_CLOCK < (int)gZ->n &&
      gZ->shape[FOLLOW_CLOCK].text[0] != '\0') {
    clock_s = gZ->shape[FOLLOW_CLOCK].text;
  }
  paint_text_map(FOLLOW_CLOCK, clock_s, 180, 220, 255);

  paint_digits(gPx[FOLLOW_VOLUME], gPw[FOLLOW_VOLUME], gPh[FOLLOW_VOLUME], polled,
               255, 255, 255, 255, true);
  memcpy(gPx[FOLLOW_DESIRE], gPx[FOLLOW_VOLUME],
         (size_t)gPw[FOLLOW_DESIRE] * (size_t)gPh[FOLLOW_DESIRE] * 4u);
  if (desired_on) {
    /* SCALE alpha 128 over the polled digits. */
    paint_digits(gPx[FOLLOW_DESIRE], gPw[FOLLOW_DESIRE], gPh[FOLLOW_DESIRE],
                 desired, 0, 255, 255, kDesireAlpha, false);
  }

  fill_px(gPx[FOLLOW_TRANSPORT], gPw[FOLLOW_TRANSPORT], gPh[FOLLOW_TRANSPORT],
          255, 255, 255, 255);
  measure(label, &tw, &th);
  ox = (gW[FOLLOW_TRANSPORT] - tw) / 2;
  oy = (gH[FOLLOW_TRANSPORT] - th) / 2;
  if (ox < 0) {
    ox = 0;
  }
  if (oy < 0) {
    oy = 0;
  }
  blit_line(gPx[FOLLOW_TRANSPORT], gPw[FOLLOW_TRANSPORT], gPh[FOLLOW_TRANSPORT],
            ox, oy, label, 0, 0, 0, 255);
}

uint8_t *follow_glass_bg_rgba(void) { return gBg; }

void follow_glass_bg_mark_dirty(void) {
  if (gZ == nullptr || FOLLOW_BASE >= (int)gZ->n) {
    return;
  }
  gZ->shape[FOLLOW_BASE].dirty = true;
  gZ->shape[FOLLOW_BASE].px = gBg;
}
