/* Draw phase1: farthest->nearest local pixmap rebuild (no panel shadow). */
#ifndef SPINME_TA_DRAW_PHASE1_H
#define SPINME_TA_DRAW_PHASE1_H

#include "ta_draw_update.h"

#ifdef __cplusplus
extern "C" {
#endif
/* Gap in px between the end of a scrolling child and its wrapped copy. */
#define TA_PHASE1_SCROLL_GAP 24

typedef struct ta_phase1_opts {
    /* Legacy single under-Cache bitmap composited under every L2R (0 = none). */
    unsigned under_shape_idx;
    /*
     * Static base (albumart / boot art) shape idx (0 = none). When set, every
     * dirty L2R / Viewport first receives the base crop under its own
     * exterior (UILayout x/y minus base_x/base_y), so after phase1 the local
     * pixmap is exactly what the glass must show there. This is the
     * "composite everything under that exterior" rule from PLAN without a
     * separate Cache shape per line.
     */
    unsigned base_shape_idx;
    int base_x;
    int base_y;
} ta_phase1_opts_t;

/*
 * Rebuild dirty shape local pixmaps farthest->nearest.
 * UILayout order: index 0 = farthest, last = nearest.
 * BitMap dirty: no-op rebuild (pixels already owned).
 * L2R dirty: clear dst, optional under/base crop, then blit children L->R.
 * Viewport dirty: rebuild dirty L2R child (transparent paper), then bake the
 *   window = base crop + child at -ox (+ wrapped copy when child wider).
 * Does not clear dirty (phase2 does). Does not allocate a panel framebuffer.
 */
int ta_draw_phase1(ta_draw_scene_t *scene, const ta_phase1_opts_t *opts);

/* Shared pack66 src-over-ish blit (A2==0 skip, else copy). */
void ta_draw_blit_bitmap(ta_pack66_t *dst, uint16_t dst_w, uint16_t dst_h,
                         int ox, int oy, const ta_shape_bitmap_t *src);

#ifdef __cplusplus
}
#endif
#endif
