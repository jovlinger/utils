/*
 * Bitmap table for the uimk2 follow view.
 *
 * A fixed table of bitmap headers. Index 0 is null and never allocated.
 * Every composited node has exactly one parent index (BM_NULL for the root).
 * Children of a container are listed in a LayoutItem slice of a shared pool;
 * the list is front to back, so items[0] is the front-most child.
 *
 * Pixel owners are the nodes with a non-NULL pixels pointer: RGBA caches and
 * the root screen buffer. Repaint composites a pixel owner's damage rect from
 * its children, front to back, with straight-alpha src-over, and writes the
 * owner's paper color under whatever the children leave uncovered.
 *
 * A Glyph node reads its alpha from read-only flash (w * h bytes, one per
 * pixel) and samples as white with that alpha. It owns no pixels.
 * Combiners are not applied yet (combiner index stays 0).
 */
#ifndef UIMK2_BITMAP_H
#define UIMK2_BITMAP_H

#include <stdint.h>

typedef enum {
    BM_KIND_NONE = 0,
    BM_KIND_RGBA,
    BM_KIND_LAYOUT,
    BM_KIND_L2R,
    BM_KIND_T2B,
    BM_KIND_VIEWPORT,
    BM_KIND_GLYPH
} BitmapKind;

#define BM_NULL 0
#define BM_MAX_NODES 64
#define BM_MAX_ITEMS 256
/* Row lists cover the root screen height (360 on the device). A root taller
 * than this, or a row pool that overflows, falls back to a full child scan. */
#define BM_MAX_ROWS 360
#define BM_ROW_POOL 2048

typedef struct {
    int16_t x, y;
    uint16_t idx;
} LayoutItem;

typedef struct {
    int16_t x, y, w, h;
} BmRect;

typedef struct {
    uint8_t kind;
    uint8_t dirty;
    uint8_t geom_dirty;
    BmRect damage;
    uint16_t parent;
    uint16_t combiner;
    uint16_t w, h;
    uint8_t *pixels;     /* w * h * 4 bytes, straight RGBA; NULL if not an owner */
    const uint8_t *glyph; /* Glyph alpha, w * h bytes in flash; NULL otherwise */
    uint8_t paper[3];    /* owner background, used where no child covers */
    uint16_t first_item; /* slice of BitmapTable.items */
    uint16_t n_items;
    int16_t ox, oy;      /* Viewport origin */
    int16_t sep;         /* L2R hsep or T2B vsep, between children */
} Bitmap;

typedef struct {
    Bitmap nodes[BM_MAX_NODES];
    LayoutItem items[BM_MAX_ITEMS];
    uint16_t n_nodes;
    uint16_t n_items;
    uint32_t child_samples; /* child samples taken by repaint */
    /* Per-row overlap lists of the one Layout pixel owner (the root). Row y
     * holds row_items[row_off[y] .. row_off[y+1]), each an item slot index of
     * that owner, front to back. Rebuilt only on repaint with geom_dirty. */
    uint16_t row_owner;
    uint8_t row_valid;
    uint32_t row_builds;
    uint16_t row_off[BM_MAX_ROWS + 1];
    uint16_t row_items[BM_ROW_POOL];
} BitmapTable;

void bm_init(BitmapTable *t);

/* Returns BM_NULL when the table is full. */
uint16_t bm_new(BitmapTable *t, uint8_t kind, uint16_t w, uint16_t h);

/* Glyph node over flash alpha (w * h bytes). Returns BM_NULL when full. */
uint16_t bm_new_glyph(BitmapTable *t, const uint8_t *alpha, uint16_t w,
                      uint16_t h);

/* Makes idx a pixel owner over px (w * h * 4 bytes). */
void bm_set_owner(BitmapTable *t, uint16_t idx, uint8_t *px,
                  const uint8_t paper[3]);

/* Copies n items into the pool as the children of parent, front to back.
 * Returns 0 if the pool is full or an item names a bad node. */
int bm_set_children(BitmapTable *t, uint16_t parent,
                    const LayoutItem *items, uint16_t n);

void bm_set_viewport_origin(BitmapTable *t, uint16_t idx, int16_t ox,
                            int16_t oy);

void bm_set_sep(BitmapTable *t, uint16_t idx, int16_t sep);

/* Lays out every L2R and T2B under idx, children first, and sets their w, h
 * and their children's LayoutItem x, y. L2R: children left to right, bottoms
 * on the tallest child's bottom edge. T2B: children top to bottom, centred on
 * the widest child (odd gaps round down). Gaps are sep between neighbours.
 * Sizes change, so the caller invalidates the node with geometry set. */
void bm_layout(BitmapTable *t, uint16_t idx);

/* Round panel clip for a size x size display, pixel centres inside the circle
 * of diameter size. Sets the inclusive x range [*x0, *x1] of row y and returns
 * 1, or returns 0 when the row has no pixel inside. */
int bm_bezel_span(int size, int y, int *x0, int *x1);

/* Unions local_rect into idx and each ancestor, in that node's coordinates. */
void bm_invalidate(BitmapTable *t, uint16_t idx, BmRect local_rect,
                   int geometry);

/* Repaints dirty descendants first, then this node's pixels if it owns any. */
void bm_repaint(BitmapTable *t, uint16_t idx);

#endif
