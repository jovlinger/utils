#include "follow_glass.h"

#include <stdlib.h>
#include <string.h>

#include <esp_heap_caps.h>

#include "glyph_file.h"
#include "layout_box.h"

static const int kPadX = 12;
static const int kPadY = 6;
static const int kButtonY = 8;
static const int kTextX = 24;
/* First row whose bezel chord still contains x = 24. */
static const int kTextY = 96;
static const int kGap = 4;
static const int kLineCap = 312;
static const int kItemCap = 96;
static const int kDesireAlpha = 128;

/* Boot stand-ins. player HTTP replaces artist, album, and title. */
static char gZone[32] = "spinme";
static char gArtist[96] = "Artist";
static char gAlbum[96] = "Album";
static char gTitle[96] = "The Long Track Name.flac";

static uint8_t *gPx[FOLLOW_COUNT];
static int gW[FOLLOW_COUNT];
static int gH[FOLLOW_COUNT];
static bool gReady = false;

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

static void measure(const char *text, int *w, int *h) {
  int tw = 0;
  int th = 0;
  if (glyph_line_size(text, &tw, &th) == 0 || tw < 1 || th < 1) {
    tw = 8;
    th = 13;
  }
  if (tw > kLineCap) {
    tw = kLineCap;
  }
  *w = tw;
  *h = th;
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
}

static void clear_desc(uimk2_shape_desc *d) { memset(d, 0, sizeof *d); }

static void place_line(uimk2_shape_desc *d, int index, int x, int y, int w,
                       int h) {
  clear_desc(d);
  d->update_selector = (uint8_t)UIMK2_UPD_FIXED;
  d->x = (int16_t)x;
  d->y = (int16_t)y;
  d->w = (uint16_t)w;
  d->h = (uint16_t)h;
  d->px = gPx[index];
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
  /* Wide enough for a polled title. The boot stand-in is shorter. */
  measure("Mg", &text_w, &text_h);
  gW[FOLLOW_ZONE] = kLineCap;
  gH[FOLLOW_ZONE] = text_h;
  gW[FOLLOW_ARTIST] = kLineCap;
  gH[FOLLOW_ARTIST] = text_h;
  gW[FOLLOW_ALBUM] = kLineCap;
  gH[FOLLOW_ALBUM] = text_h;
  gW[FOLLOW_TITLE] = kLineCap;
  gH[FOLLOW_TITLE] = text_h;
  measure("888", &text_w, &text_h);
  gW[FOLLOW_VOLUME] = text_w;
  gH[FOLLOW_VOLUME] = text_h;
  gW[FOLLOW_DESIRE] = text_w;
  gH[FOLLOW_DESIRE] = text_h;
  for (i = 0; i < FOLLOW_COUNT; ++i) {
    gPx[i] = nullptr;
  }
  gPx[FOLLOW_TRANSPORT] = alloc_px(gW[FOLLOW_TRANSPORT], gH[FOLLOW_TRANSPORT]);
  gPx[FOLLOW_DESIRE] = alloc_px(gW[FOLLOW_DESIRE], gH[FOLLOW_DESIRE]);
  gPx[FOLLOW_VOLUME] = alloc_px(gW[FOLLOW_VOLUME], gH[FOLLOW_VOLUME]);
  gPx[FOLLOW_TITLE] = alloc_px(gW[FOLLOW_TITLE], gH[FOLLOW_TITLE]);
  gPx[FOLLOW_ALBUM] = alloc_px(gW[FOLLOW_ALBUM], gH[FOLLOW_ALBUM]);
  gPx[FOLLOW_ARTIST] = alloc_px(gW[FOLLOW_ARTIST], gH[FOLLOW_ARTIST]);
  gPx[FOLLOW_ZONE] = alloc_px(gW[FOLLOW_ZONE], gH[FOLLOW_ZONE]);
  for (i = FOLLOW_TRANSPORT; i <= FOLLOW_ZONE; ++i) {
    if (gPx[i] == nullptr) {
      return false;
    }
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

  clear_desc(&desc[FOLLOW_BASE]);
  desc[FOLLOW_BASE].update_selector = (uint8_t)UIMK2_UPD_FIXED;
  desc[FOLLOW_BASE].is_base = true;
  desc[FOLLOW_BASE].w = (uint16_t)PANEL_W;
  desc[FOLLOW_BASE].h = (uint16_t)PANEL_H;
  desc[FOLLOW_BASE].rgba[3] = 255;

  /* desc[] is indexed by z-order, which matches FOLLOW_* . */
  if (!uimk2_zlist_build(z, desc, (uint16_t)FOLLOW_COUNT, curr, next, ring, ping,
                         ctx)) {
    return false;
  }
  gReady = true;
  follow_glass_raster(0, 0, false, false);
  return true;
}

static void paint_digits(uint8_t *dst, int w, int h, int value, uint8_t r,
                         uint8_t g, uint8_t b, int scale, bool clear) {
  char text[8];
  if (clear) {
    fill_px(dst, w, h, 0, 0, 0, 255);
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
  int tw = 0;
  int th = 0;
  int ox;
  int oy;
  if (!gReady) {
    return;
  }
  fill_px(gPx[FOLLOW_ZONE], gW[FOLLOW_ZONE], gH[FOLLOW_ZONE], 0, 0, 0, 255);
  blit_line(gPx[FOLLOW_ZONE], gW[FOLLOW_ZONE], gH[FOLLOW_ZONE], 0, 0, gZone, 255,
            255, 0, 255);
  fill_px(gPx[FOLLOW_ARTIST], gW[FOLLOW_ARTIST], gH[FOLLOW_ARTIST], 0, 0, 0, 255);
  blit_line(gPx[FOLLOW_ARTIST], gW[FOLLOW_ARTIST], gH[FOLLOW_ARTIST], 0, 0,
            gArtist, 255, 255, 255, 255);
  fill_px(gPx[FOLLOW_ALBUM], gW[FOLLOW_ALBUM], gH[FOLLOW_ALBUM], 0, 0, 0, 255);
  blit_line(gPx[FOLLOW_ALBUM], gW[FOLLOW_ALBUM], gH[FOLLOW_ALBUM], 0, 0, gAlbum,
            255, 255, 255, 255);
  fill_px(gPx[FOLLOW_TITLE], gW[FOLLOW_TITLE], gH[FOLLOW_TITLE], 0, 0, 0, 255);
  blit_line(gPx[FOLLOW_TITLE], gW[FOLLOW_TITLE], gH[FOLLOW_TITLE], 0, 0, gTitle,
            255, 255, 255, 255);

  paint_digits(gPx[FOLLOW_VOLUME], gW[FOLLOW_VOLUME], gH[FOLLOW_VOLUME], polled,
               255, 255, 255, 255, true);
  memcpy(gPx[FOLLOW_DESIRE], gPx[FOLLOW_VOLUME],
         (size_t)gW[FOLLOW_DESIRE] * (size_t)gH[FOLLOW_DESIRE] * 4u);
  if (desired_on) {
    /* SCALE alpha 128 over the polled digits. Stored opaque so replace-blit
     * keeps the mix. */
    paint_digits(gPx[FOLLOW_DESIRE], gW[FOLLOW_DESIRE], gH[FOLLOW_DESIRE],
                 desired, 0, 255, 255, kDesireAlpha, false);
  }

  fill_px(gPx[FOLLOW_TRANSPORT], gW[FOLLOW_TRANSPORT], gH[FOLLOW_TRANSPORT], 255,
          255, 255, 255);
  measure(label, &tw, &th);
  ox = (gW[FOLLOW_TRANSPORT] - tw) / 2;
  oy = (gH[FOLLOW_TRANSPORT] - th) / 2;
  if (ox < 0) {
    ox = 0;
  }
  if (oy < 0) {
    oy = 0;
  }
  blit_line(gPx[FOLLOW_TRANSPORT], gW[FOLLOW_TRANSPORT], gH[FOLLOW_TRANSPORT], ox,
            oy, label, 0, 0, 0, 255);
}
