/* Draw phase1: farthest->nearest local pixmap rebuild (no panel shadow). */
#ifndef SPINME_TA_DRAW_PHASE1_H
#define SPINME_TA_DRAW_PHASE1_H

#include "ta_draw_update.h"

/* Optional under-image shape idx (0 = none) composited under L2R text. */
typedef struct ta_phase1_opts {
    unsigned under_shape_idx; /* bitmap under-Cache; 0 disables */
} ta_phase1_opts_t;

/*
 * Rebuild dirty shape local pixmaps farthest->nearest.
 * UILayout order: index 0 = farthest, last = nearest.
 * BitMap dirty: no-op rebuild (pixels already owned).
 * L2R dirty: clear dst then blit children L->R; if under set, blit under first.
 * Does not clear dirty (phase2 does). Does not allocate a panel framebuffer.
 */
int ta_draw_phase1(ta_draw_scene_t *scene, const ta_phase1_opts_t *opts);

#endif
