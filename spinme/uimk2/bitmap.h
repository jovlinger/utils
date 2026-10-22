/* Bitmap table and compositor for uimk2. Host-testable, no libc allocation.
 * See todo 2d255758 (uimk2 bitmap compositor): Bitmap table, What is cached,
 * Dirty and repaint. */
#ifndef UIMK2_BITMAP_H
#define UIMK2_BITMAP_H

#include <stdint.h>

typedef enum {
  BM_NULL = 0,
  BM_RGBA,
  BM_LAYOUT,
  BM_L2R,
  BM_T2B,
  BM_VIEWPORT,
  BM_GLYPH
} BitmapKind;

typedef struct {
  int32_t x, y, w, h;
} Rect; /* empty when w == 0 or h == 0 */

typedef struct {
  int16_t x, y;
  uint16_t idx;
} LayoutItem;

/* One header per node. Every composited node has exactly one parent index.
 * Fields beyond the common ones are used by the kinds that name them. */
typedef struct {
  uint8_t kind; /* BitmapKind */
  uint8_t dirty;
  uint8_t geom_dirty;
  uint16_t parent; /* 0 = no parent (a root) */
  uint16_t combiner; /* 0 = none; applied by the combiner item */
  int32_t w, h;
  Rect damage;

  /* Pixel owner (RGBA, or a root Layout): w*h*4 bytes, straight alpha RGBA,
   * and the paper color written where no child covers a damaged pixel. */
  uint8_t *pix;
  uint8_t paper[4];

  /* RGBA line cache with content: the node whose subtree repaints into pix. */
  uint16_t child;

  /* Layout: items in back-to-front order (a later item is in front). */
  const LayoutItem *items;
  uint16_t nitems;

  /* Root Layout: per-row overlap lists in caller storage. Row y owns
   * rowlist[y * rowcap ...], a zero-terminated list of the child indexes
   * whose box covers y, back to front. rowcap counts the terminator.
   * Rebuilt by bm_repaint only when geom_dirty is set. */
  uint16_t *rowlist;
  uint16_t rowcap;
  uint8_t rows_valid;

  /* L2R / T2B: zero-terminated child index list and separator. */
  const uint16_t *list;
  int32_t sep;

  /* Viewport: one child (see child) sampled at (ox + x, oy + y). */
  int32_t ox, oy;

  /* Glyph: read-only alpha bytes, w*h, RGB constant white. */
  const uint8_t *alpha;
  uint16_t codepoint;
} Bitmap;

/* Color combiner table entry. mask bit 0 R, 1 G, 2 B, 3 A; value is one byte
 * per channel in R, G, B, A order. Only COMB_SET is applied so far. */
typedef enum { COMB_SET = 0, COMB_SCALE, COMB_CURVE } CombinerOp;

typedef struct {
  uint8_t mask;
  uint8_t op; /* CombinerOp */
  uint8_t value[4];
} Combiner;

typedef struct {
  Bitmap *b;      /* b[0] is the null header; the table is not terminated */
  uint16_t n;
  uint32_t samples; /* leaf reads (RGBA pixel or Glyph alpha); test probe */
  const Combiner *combiners; /* indexed by Bitmap.combiner; [0] unused */
  uint16_t ncombiners;
  uint32_t row_rebuilds; /* per-row list rebuilds; test probe */
} BitmapTable;

Rect rect_union(Rect a, Rect b);
int rect_empty(Rect r);

/* Set w, h of an L2R or T2B node from its children (children measured
 * first). L2R: sum of widths plus seps, max height. T2B: max width, sum of
 * heights plus seps. */
void bm_measure(BitmapTable *t, uint16_t idx);

/* Offset of child inside parent, in parent coordinates. Returns 0 on
 * success, -1 when child is not in parent. */
int bm_child_offset(const BitmapTable *t, uint16_t parent, uint16_t child,
                    int32_t *ox, int32_t *oy);

/* Union local_rect into node.damage, set dirty, or geom_dirty with geometry,
 * map the rect into the parent, repeat up the parent indexes to the root. */
void bm_invalidate(BitmapTable *t, uint16_t idx, Rect local_rect,
                   int geometry);

/* Repaint from idx. A clean node returns. Dirty children first, then each
 * pixel in an owner's damage rect is composited front to back (straight
 * alpha src-over, stopping at accumulator alpha 255); an uncovered pixel
 * becomes paper. Clears dirty, geom_dirty, and damage. */
void bm_repaint(BitmapTable *t, uint16_t idx);

/* Rebuild a Layout's per-row overlap lists from its items. Returns 0, or -1
 * when the node has no row storage or a row would not fit rowcap. */
int bm_build_rows(BitmapTable *t, uint16_t idx);

/* Round bezel: the largest circle inside a w x h panel. Sets the half-open
 * pixel span [*x0, *x1) of row y inside the circle (pixel centers); an empty
 * row gives x0 == x1. */
void bm_bezel_span(int32_t w, int32_t h, int32_t y, int32_t *x0, int32_t *x1);

/* Blit callback: len pixels of straight-alpha RGBA starting at (x, y). */
typedef void (*BlitFn)(void *ctx, int32_t x, int32_t y, int32_t len,
                       const uint8_t *rgba);

/* Blit rect (clamped to the owner's pixels) of an owner node row by row,
 * clipped to the round bezel. The clip is applied here, at blit time; the
 * pixels in the buffer are untouched. */
void bm_blit_bezel(const BitmapTable *t, uint16_t idx, Rect r, BlitFn fn,
                   void *ctx);

#endif
