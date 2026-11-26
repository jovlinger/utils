/* Under-image invalidation: base dirty rebuilds under; scroll/clock alone does not. */
#ifndef SPINME_TA_UNDER_IMAGE_H
#define SPINME_TA_UNDER_IMAGE_H

#include "ta_draw_update.h"

#include <stdint.h>

typedef struct ta_under_cache {
    unsigned under_shape_idx; /* ShapeBitMap under-Cache */
    unsigned base_shape_idx;  /* albumart/base that owns under */
    uint8_t under_valid;      /* 1 when under matches current base */
} ta_under_cache_t;

void ta_under_reset(ta_under_cache_t *u);

/*
 * Call after Draw.update.
 * - If base Shape.dirty: mark under dirty and under_valid=0.
 * - If only overlay (scroll/clock) dirty and exterior unchanged: leave under.
 * Returns 1 if under needs phase1 rebuild, 0 otherwise, -1 on error.
 */
int ta_under_after_update(ta_under_cache_t *u, ta_draw_scene_t *scene,
                          unsigned overlay_shape_idx, int overlay_box_moved);

#endif
