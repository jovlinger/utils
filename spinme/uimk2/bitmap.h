/* Bitmap tree and repaint for the uimk2 compositor. See spinme/uimk2.txt.
 * A fixed table of headers; index 0 is null. Only RGBA nodes and the root
 * Layout own pixels (the caller supplies the buffer). Every other kind is
 * sampled through its children. Each node has exactly one parent index. */
#ifndef UIMK2_BITMAP_H
#define UIMK2_BITMAP_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
  BK_NONE = 0,
  BK_RGBA,
  BK_LAYOUT,
  BK_L2R,
  BK_T2B,
  BK_VIEWPORT,
  BK_GLYPH
} BitmapKind;

/* Straight alpha, 8-bit channels. */
typedef struct {
  uint8_t r, g, b, a;
} Px;

typedef struct {
  int16_t x, y, w, h;
} Rect;

/* Color combiner table entry. mask bit 0 R, 1 G, 2 B, 3 A; value is R,G,B,A. */
typedef enum { CB_SET = 0, CB_SCALE, CB_CURVE } CombinerOp;
typedef struct {
  uint8_t mask;
  uint8_t op;
  uint8_t value[4];
} Combiner;

/* Apply one combiner to a sample. Per channel in the mask, c the channel and
 * v its value byte: SET c = v; SCALE c = c * v / 255 rounded to nearest;
 * CURVE c' = c + (v - 128) * c * (255 - c) / 32768 clamped to 0..255.
 * Channels outside the mask pass through. */
Px bitmap_combine(const Combiner *c, Px p);

typedef struct {
  int16_t x, y;
  uint16_t idx;
} LayoutItem;

typedef struct {
  uint8_t kind;
  bool dirty;
  bool geom_dirty;
  Rect damage;        /* in this node's coordinates; w == 0 means empty */
  uint16_t parent;    /* 0 = none */
  uint8_t combiner;   /* 0 = none */
  uint16_t w, h;
  Px *pixels;         /* RGBA and root Layout only; w*h entries */
  Px paper;           /* color of a damaged pixel no child covers */
  LayoutItem *items;  /* Layout, L2R, T2B children, back to front */
  uint16_t nitems, items_cap;
  int16_t hsep, vsep; /* L2R and T2B separators */
  uint16_t child;     /* Viewport child, or RGBA content child (0 = none) */
  int16_t ox, oy;     /* Viewport origin */
  const uint8_t *alpha; /* Glyph: w*h coverage bytes, read-only, RGB white */
  unsigned repaints;  /* times this node wrote its pixels */
  /* Root Layout per-row overlap lists (CSR). Caller supplies row_start
   * (h + 1 entries) and row_items (row_cap entries); row_items holds item
   * positions in items[], back to front within a row. NULL row_start means
   * no lists: repaint walks every child. */
  uint16_t *row_start;
  uint16_t *row_items;
  uint16_t row_cap;
  bool rows_built;
  unsigned rebuilds;  /* times the lists were rebuilt */
} Bitmap;

typedef struct {
  Bitmap *b;
  uint16_t cap;       /* table entries, including the null entry 0 */
  uint16_t used;      /* next free index */
  const Combiner *comb; /* sealed table; index 0 is none */
  uint16_t ncomb;
  unsigned long samples; /* leaf samples taken while repainting */
} BitmapTable;

void bitmap_table_init(BitmapTable *t, Bitmap *storage, uint16_t cap);

/* Returns the new index, or 0 when the table is full. */
uint16_t bitmap_new(BitmapTable *t, BitmapKind kind, uint16_t w, uint16_t h);

/* Append child to a Layout, L2R, or T2B at (x, y) in the parent. Refused
 * (false) when the child already has a parent or the list is full. */
bool bitmap_add(BitmapTable *t, uint16_t parent, uint16_t child, int16_t x,
                int16_t y);

/* Set the single child of a Viewport or the content child of an RGBA node.
 * Refused (false) when the child already has a parent. */
bool bitmap_set_child(BitmapTable *t, uint16_t parent, uint16_t child);

/* Recompute child offsets and own size of an L2R or T2B from the children. */
void bitmap_pack(BitmapTable *t, uint16_t idx);

/* Union local_rect into node.damage, set dirty, or geom_dirty with geometry,
 * transform the rect into the parent, and repeat up to the root. Walks parent
 * indexes only; never searches down. */
void bitmap_invalidate(BitmapTable *t, uint16_t idx, Rect local_rect,
                       bool geometry);

/* Repaint dirty children first, then write this node's damage rect when it
 * owns pixels, then clear dirty, geom_dirty, and damage. A clean node returns. */
void bitmap_repaint(BitmapTable *t, uint16_t idx);

/* Receives one run of n pixels starting at panel (x, y). */
typedef void (*BlitSpanFn)(void *ctx, int x, int y, int n, const Px *px);

/* Round bezel clip at blit time: sends the part of `damage` (root
 * coordinates) inside the circle inscribed in a diameter x diameter screen,
 * one span per row. A pixel is inside when its center is within the circle. */
void bitmap_blit_round(const Bitmap *root, Rect damage, int diameter,
                       BlitSpanFn fn, void *ctx);

#endif
