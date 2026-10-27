#pragma once

/* Left-to-right and top-to-bottom box composition.
 * The result origin is the center of the tight bounding box.
 * Child (cx, cy) is that child's center in the result frame.
 * Keep this in step with screenmock/compose.py.
 *
 * English text is l2r(glyphs, bot), then t2b(lines, left). The caller
 * puts the union center on the glass center, so the block is vcentered
 * and the lines share a left edge.
 */

enum VAlign {
  VAlign_top = 0,
  VAlign_vcenter = 1,
  VAlign_bot = 2,
};

enum HAlign {
  HAlign_left = 0,
  HAlign_hcenter = 1,
  HAlign_right = 2,
};

struct LayBox {
  int w;
  int h;
};

struct LayAt {
  int cx;
  int cy;
  int w;
  int h;
};

struct LayUnion {
  int x;
  int y;
  int w;
  int h;
};

inline int lay_left(const LayAt *at) { return at->cx - at->w / 2; }

inline int lay_top(const LayAt *at) { return at->cy - at->h / 2; }

/* Zero-area spacers. Callers insert these into l2r / t2b. */
inline LayBox lay_hshim(int px) {
  LayBox box;
  box.w = px;
  box.h = 0;
  return box;
}

inline LayBox lay_vshim(int px) {
  LayBox box;
  box.w = 0;
  box.h = px;
  return box;
}

inline int lay_align_start(int span, int size, int mode) {
  if (mode == 0) {
    return 0;
  }
  if (mode == 1) {
    return (span - size) / 2;
  }
  return span - size;
}

inline void lay_clear(LayUnion *result) {
  result->x = 0;
  result->y = 0;
  result->w = 0;
  result->h = 0;
}

inline void lay_l2r(const LayBox *boxes, int n, VAlign valign, LayAt *out,
                    LayUnion *result) {
  if (n <= 0) {
    lay_clear(result);
    return;
  }
  int main_span = 0;
  int cross = 0;
  for (int i = 0; i < n; ++i) {
    main_span += boxes[i].w;
    if (boxes[i].h > cross) {
      cross = boxes[i].h;
    }
  }
  const int origin_main = main_span / 2;
  const int origin_cross = cross / 2;
  int cursor = 0;
  for (int i = 0; i < n; ++i) {
    const int cross_at = lay_align_start(cross, boxes[i].h, (int)valign);
    out[i].w = boxes[i].w;
    out[i].h = boxes[i].h;
    out[i].cx = cursor + boxes[i].w / 2 - origin_main;
    out[i].cy = cross_at + boxes[i].h / 2 - origin_cross;
    cursor += boxes[i].w;
  }
  result->x = -origin_main;
  result->y = -origin_cross;
  result->w = main_span;
  result->h = cross;
}

inline void lay_t2b(const LayBox *boxes, int n, HAlign halign, LayAt *out,
                    LayUnion *result) {
  if (n <= 0) {
    lay_clear(result);
    return;
  }
  int main_span = 0;
  int cross = 0;
  for (int i = 0; i < n; ++i) {
    main_span += boxes[i].h;
    if (boxes[i].w > cross) {
      cross = boxes[i].w;
    }
  }
  const int origin_main = main_span / 2;
  const int origin_cross = cross / 2;
  int cursor = 0;
  for (int i = 0; i < n; ++i) {
    const int cross_at = lay_align_start(cross, boxes[i].w, (int)halign);
    out[i].w = boxes[i].w;
    out[i].h = boxes[i].h;
    out[i].cx = cross_at + boxes[i].w / 2 - origin_cross;
    out[i].cy = cursor + boxes[i].h / 2 - origin_main;
    cursor += boxes[i].h;
  }
  result->x = -origin_cross;
  result->y = -origin_main;
  result->w = cross;
  result->h = main_span;
}

/* One clipped slice of the background. x,y are viewport top-left coordinates.
 * src_x, src_y index the background. Keep this in step with screenmock/compose.py.
 */
struct MarqueeTile {
  int x;
  int y;
  int w;
  int h;
  int src_x;
  int src_y;
};

struct HMarquee {
  int w;
  int h;
};

/* Slide the viewport across the background by t pixels. The background
 * repeats end to start, so the join has no extra gap. A trailing blank
 * shows up only when that blank is already part of the background.
 * Returns the number of tiles written.
 */
inline int lay_hmarquee(LayBox viewport, LayBox background, int t,
                        MarqueeTile *tiles, int cap, HMarquee *result) {
  const int view_w = viewport.w > 0 ? viewport.w : 0;
  const int view_h = viewport.h > 0 ? viewport.h : 0;
  const int back_w = background.w > 0 ? background.w : 0;
  const int back_h = background.h > 0 ? background.h : 0;
  int tile_h = back_h < view_h ? back_h : view_h;
  if (tile_h < 0) {
    tile_h = 0;
  }
  result->w = view_w;
  result->h = view_h;
  int n = 0;
  if (back_w <= 0 || tile_h <= 0 || view_w <= 0 || tiles == nullptr || cap <= 0) {
    return 0;
  }
  int offset = t % back_w;
  if (offset < 0) {
    offset += back_w;
  }
  int x = 0;
  int src = offset;
  while (x < view_w && n < cap) {
    int run = back_w - src;
    if (run > view_w - x) {
      run = view_w - x;
    }
    tiles[n].x = x;
    tiles[n].y = 0;
    tiles[n].w = run;
    tiles[n].h = tile_h;
    tiles[n].src_x = src;
    tiles[n].src_y = 0;
    n++;
    x += run;
    src = 0;
  }
  return n;
}
