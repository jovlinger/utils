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

typedef struct {
    uimk2_bm *bm;    /* bm[0] is the null header */
    uint16_t cap;    /* headers in bm */
    uint16_t count;  /* next free index */
    uint16_t root;   /* index of the root Layout */
    uint32_t samples; /* child samples taken by repaint, for tests */
} uimk2_bmtab;

void uimk2_bmtab_init(uimk2_bmtab *t, uimk2_bm *storage, uint16_t cap);

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

/* Repaint from the root. Returns the root damage rect that was written (the
 * panel blit rect); empty when the frame was clean. */
uimk2_rect uimk2_repaint(uimk2_bmtab *t);

uimk2_rect uimk2_rect_union(uimk2_rect a, uimk2_rect b);

#endif /* UIMK2_BITMAP_H */
