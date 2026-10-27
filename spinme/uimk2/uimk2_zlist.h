/* uimk2 host zlist: update, then render into next, then ping Core A.
 *
 * Index 0 is closest to the viewer. Draw walks the high index down to 0.
 * A shape stores child indices only; there is no parent index. Exterior
 * (x, y, w, h) and that child list are sealed at build. Update changes
 * dynamic fields only (scroll origin, clock text) and sets dirty when
 * those details change.
 *
 * mark_dirty_from_children walks children first, then sets this shape
 * dirty if any child is dirty. Render does not consult Cache and does
 * not clear next. The base shape (farthest, a full-frame static RGBA)
 * is painted with a memcpy into next; closer shapes draw over it.
 * Drawing a shape clears its dirty bit.
 *
 * update_render_draw is the one entry: update every shape, mark dirty
 * from each root, render into next, then compare. When busy-by-core-A
 * is set, a redraw retry is pushed on the event ring (attempt += 1,
 * ERROR at REDRAW_ATTEMPT_CAP) and curr is left alone. Otherwise the
 * PANEL_H-bit row bitmap is filled from the curr/next diff. Any set
 * bit swaps the two buffers, sets busy, and pings A.
 *
 * The follow-view Cache path is a different module and is not used here.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_ZLIST_H
#define UIMK2_ZLIST_H

#include <stdbool.h>
#include <stdint.h>

#include "uimk2_config.h"
#include "uimk2_event.h"

#define UIMK2_ZLIST_MAX 16u
#define UIMK2_SHAPE_MAX_CHILDREN 8u
#define UIMK2_ZLIST_TEXT 32u
#define UIMK2_FRAME_BYTES (PANEL_W * PANEL_H * 4u)

/* Function selector for shape update. Dispatch is a switch. */
typedef enum {
    UIMK2_UPD_FIXED = 0, /* return; dirty stays as it was */
    UIMK2_UPD_SCROLL,    /* step the viewport origin */
    UIMK2_UPD_CLOCKTEXT  /* rewrite the string from the clock */
} uimk2_update_sel;

/* Host stand-in for Core A.redraw(). Not a shape dispatch. */
typedef void (*uimk2_zlist_ping_fn)(void *ctx);

typedef struct {
    uint8_t update_selector; /* uimk2_update_sel */
    bool dirty;
    bool is_base; /* farthest layer: full-frame RGBA memcpy into next */
    int16_t x, y; /* position, sealed at build */
    uint16_t w, h; /* exterior box, sealed at build */
    int16_t ox, oy; /* scroll viewport origin */
    int16_t step_x, step_y; /* added to the origin on each scroll update */
    uint16_t child[UIMK2_SHAPE_MAX_CHILDREN]; /* child indices, no parent */
    uint16_t nchild;
    const uint8_t *px; /* static RGBA, or NULL to paint rgba[] */
    uint8_t rgba[4];
    char text[UIMK2_ZLIST_TEXT]; /* clocktext sketch */
} uimk2_shape;

/* Build input. children is copied; the pointer is not kept. */
typedef struct {
    uint8_t update_selector;
    bool is_base;
    int16_t x, y;
    uint16_t w, h;
    int16_t step_x, step_y;
    const uint16_t *children;
    uint16_t nchildren;
    const uint8_t *px;
    uint8_t rgba[4];
} uimk2_shape_desc;

typedef struct {
    uimk2_shape shape[UIMK2_ZLIST_MAX];
    uint16_t n; /* zlist length; index 0 is closest */
    uint16_t root[UIMK2_ZLIST_MAX]; /* shapes that are not anyone's child */
    uint16_t nroot;
    uint8_t *curr; /* panel buffer A is pushing */
    uint8_t *next; /* buffer B paints; A does not see it */
    /* One bit per row. Bit y lives in byte y/8, low bit = lower row. */
    uint8_t row_dirty[(PANEL_H + 7u) / 8u];
    bool busy; /* busy-by-core-A; A clears it, B only sets it */
    int redraw_attempt;
    uimk2_ring *ring; /* redraw retries; NULL skips the push */
    uimk2_zlist_ping_fn ping_a;
    void *ping_ctx;
    int32_t clock_sec;
    uint32_t clock_tick;
} uimk2_zlist;

/* Copy desc[0..n) in order (index 0 closest), seal exterior and children,
 * and record roots. curr and next are each UIMK2_FRAME_BYTES, caller-owned.
 * False when the list, a child index, or a child cycle does not fit;
 * *z is then zero. */
bool uimk2_zlist_build(uimk2_zlist *z, const uimk2_shape_desc *desc, uint16_t n,
                       uint8_t *curr, uint8_t *next, uimk2_ring *ring,
                       uimk2_zlist_ping_fn ping_a, void *ping_ctx);

/* Logical second and absolute tick for the clocktext arm. */
void uimk2_zlist_set_clock(uimk2_zlist *z, int32_t sec, uint32_t tick);

/* Per-shape selector. Does not write pixels. */
void uimk2_zlist_update(uimk2_zlist *z);

/* Recurse over children, then set dirty if any child is dirty.
 * Does not clear dirty. idx outside the list does nothing. */
void uimk2_zlist_mark_dirty_from_children(uimk2_zlist *z, uint16_t idx);

/* Distant-first paint into next. Does not clear next. Clears dirty
 * on each shape after it is painted. A base shape memcpy's its static
 * RGBA (or stamps rgba[] when px is NULL) over the whole frame. */
void uimk2_zlist_render(uimk2_zlist *z);

/* Update, mark from roots, render, then compare / swap / ping.
 * On busy-by-core-A, push a redraw retry and return before the compare. */
void uimk2_zlist_update_render_draw(uimk2_zlist *z);

/* REDRAW event: retry the compare / swap / ping. attempt is the value
 * carried on the event. Still busy: push attempt + 1. Does not render. */
void uimk2_zlist_redraw(uimk2_zlist *z, int attempt);

/* Row y of the dirty bitmap. False when y is outside the panel. */
bool uimk2_zlist_row_dirty(const uimk2_zlist *z, uint16_t y);

#endif /* UIMK2_ZLIST_H */
