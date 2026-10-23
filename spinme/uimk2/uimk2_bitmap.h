/* uimk2 bitmap table: the node kinds, invalidate, and repaint.
 *
 * A fixed table of bitmap headers; index 0 is null. Every composited node
 * has exactly one parent index. invalidate walks parent indexes up to the
 * root; repaint starts at the root and recomposes only damage.
 *
 * Only RGBA nodes and the root Layout own pixels. Layout (other than the
 * root), L2R, T2B, Viewport, and Glyph keep no raster: they are sampled
 * through their children when an owner is repainted.
 *
 * Pixels are straight-alpha RGBA, 8 bits per channel, bytes in R, G, B, A
 * order. A sample outside a node's box is a miss, not a color; (0,0,0,0)
 * inside the box is a real color.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_BITMAP_H
#define UIMK2_BITMAP_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    UIMK2_BM_NULL = 0,
    UIMK2_BM_RGBA,
    UIMK2_BM_LAYOUT,
    UIMK2_BM_L2R,
    UIMK2_BM_T2B,
    UIMK2_BM_VIEWPORT,
    UIMK2_BM_GLYPH
} uimk2_bm_kind;

typedef struct {
    int16_t x, y;
    uint16_t w, h; /* w == 0 or h == 0 is the empty rect */
} uimk2_rect;

/* A child placed in a Layout's coordinates. */
typedef struct {
    int16_t x, y;
    uint16_t idx;
} uimk2_layout_item;

typedef struct {
    uint8_t kind;      /* uimk2_bm_kind */
    bool dirty;
    bool geom_dirty;
    /* Hint, default false: the caller-provided pixel buffer (rgba.px or
     * layout.px) is a finished picture of this subtree whenever the node is
     * clean. A parent's sample of a clean hinted node with a buffer reads
     * those bytes and never composites the node's children. A dirty hinted
     * node is recomposed into its buffer by repaint, children first, before
     * its parent samples it. The library never allocates the buffer. Glyphs
     * have no buffer, so the hint does nothing for them. */
    bool cache_backing;
    uint8_t combiner;  /* 0 = none */
    uimk2_rect damage; /* in this node's coordinates */
    uint16_t parent;   /* 0 = root (or detached) */
    uint16_t w, h;
    union {
        struct {
            uint8_t *px;    /* w * h * 4 bytes */
            uint16_t child; /* content repainted into px; 0 = plain raster */
            uint8_t paper[4];
        } rgba;
        struct {
            const uimk2_layout_item *items; /* back to front */
            uint16_t n;
            uint8_t *px; /* root only: the screen buffer, w * h * 4 */
            uint8_t paper[4];
            /* Root only, optional: per-row overlap lists. Row y lists the
             * positions in items[] of the items whose box overlaps y,
             * front to back, at row_item[row_start[y] .. row_start[y+1]).
             * row_start has h + 1 entries and row_item row_cap entries.
             * Rebuilt by repaint when geom_dirty is set or rows_ok is
             * false. With no storage, or when the lists do not fit in
             * row_cap, repaint walks every item. */
            uint32_t *row_start;
            uint16_t *row_item;
            uint32_t row_cap;
            bool rows_ok;
        } layout;
        struct {
            const uint16_t *items; /* IdxList: zero-terminated */
            uint16_t sep;          /* hsep for L2R, vsep for T2B */
        } pack;
        struct {
            uint16_t child;
            int16_t ox, oy;
        } viewport;
        struct {
            const uint8_t *alpha; /* w * h coverage bytes, read-only */
        } glyph;
    } u;
} uimk2_bm;

/* Color combiner channel mask bits; value[] is in R, G, B, A order. */
#define UIMK2_COMB_R 0x1u
#define UIMK2_COMB_G 0x2u
#define UIMK2_COMB_B 0x4u
#define UIMK2_COMB_A 0x8u
#define UIMK2_COMB_RGB (UIMK2_COMB_R | UIMK2_COMB_G | UIMK2_COMB_B)

typedef enum {
    UIMK2_COMB_SET = 0,   /* c = v */
    UIMK2_COMB_SCALE = 1, /* c = c * v / 255, rounded to nearest */
    UIMK2_COMB_CURVE = 2  /* c += (v - 128) * c * (255 - c) / 32768, clamped;
                           * 0 and 255 are fixed, v = 128 is the identity */
} uimk2_comb_op;

/* Applied to every sample of a node before it is blended into its parent.
 * Channels outside mask pass through unchanged. */
typedef struct {
    uint8_t mask; /* UIMK2_COMB_* bits */
    uint8_t op;   /* uimk2_comb_op */
    uint8_t value[4];
} uimk2_combiner;

typedef struct {
    uimk2_bm *bm;    /* bm[0] is the null header */
    uint16_t cap;    /* headers in bm */
    uint16_t count;  /* next free index */
    uint16_t root;   /* index of the root Layout */
    uint32_t samples; /* child samples taken by repaint, for tests */
    uint32_t row_rebuilds; /* root overlap-list rebuilds, for tests */
    const uimk2_combiner *comb; /* comb[0] is unused: index 0 = none */
    uint16_t ncomb;             /* entries in comb */
} uimk2_bmtab;

void uimk2_bmtab_init(uimk2_bmtab *t, uimk2_bm *storage, uint16_t cap);

/* Install the fixed combiner table. A header combiner index of 0, or one at
 * or past n, applies nothing. */
void uimk2_bmtab_set_combiners(uimk2_bmtab *t, const uimk2_combiner *comb,
                               uint16_t n);

/* Apply combiner index ci of t to the sample s in place. */
void uimk2_combine(const uimk2_bmtab *t, uint8_t ci, uint8_t s[4]);

/* A zeroed header of kind; returns its index, or 0 when the table is full. */
uint16_t uimk2_bm_new(uimk2_bmtab *t, uimk2_bm_kind kind);

/* Set w and h of an L2R or T2B from its children: L2R width is the sum of
 * child widths plus seps and height is the max child height; T2B is the
 * transpose. Measure children first. */
void uimk2_bm_measure(uimk2_bmtab *t, uint16_t idx);

/* Offset of child within parent, in parent coordinates. Returns false when
 * child is not a child of parent. L2R children are bottom-aligned, T2B
 * children centered on the cross axis; a Viewport child sits at
 * (-ox, -oy). */
bool uimk2_bm_child_offset(const uimk2_bmtab *t, uint16_t parent,
                           uint16_t child, int32_t *dx, int32_t *dy);

/* Union local_rect into node's damage, set dirty, or geom_dirty with
 * geometry, transform the rect into the parent, and repeat up to the root.
 * The rect is clipped to each node's box. */
void uimk2_invalidate(uimk2_bmtab *t, uint16_t node, uimk2_rect local_rect,
                      bool geometry);

/* Scroll a Viewport: add dx to its ox and dy to its oy (each sum clamped to
 * int16), then invalidate the whole viewport box {0, 0, w, h}. There is no
 * pixel move and no exposed-slab bookkeeping: every window pixel is damage
 * and repaint resamples it. dx == 0 and dy == 0 do nothing, as does an
 * index that is not a Viewport. */
void uimk2_view_scroll(uimk2_bmtab *t, uint16_t viewport, int32_t dx,
                       int32_t dy);

/* Repaint from the root. Returns the root damage rect that was written (the
 * panel blit rect); empty when the frame was clean. */
uimk2_rect uimk2_repaint(uimk2_bmtab *t);

uimk2_rect uimk2_rect_union(uimk2_rect a, uimk2_rect b);

/* The round bezel, a clip applied at blit time. The visible disc of a w x h
 * panel has diameter min(w, h) and is centered on the panel; pixel (x, y)
 * is visible when its center lies in the disc:
 * (2x + 1 - w)^2 + (2y + 1 - h)^2 <= min(w, h)^2. */
bool uimk2_bezel_visible(uint16_t w, uint16_t h, int32_t x, int32_t y);

/* The visible span of row y of a w x h panel inside the blit rect r:
 * columns [*x0, *x1). Returns false (and an empty span) when row y of r has
 * no visible pixel. The blit sends, for each row of the root damage rect,
 * only this span. */
bool uimk2_bezel_span(uint16_t w, uint16_t h, uimk2_rect r, int32_t y,
                      int32_t *x0, int32_t *x1);

#endif /* UIMK2_BITMAP_H */
