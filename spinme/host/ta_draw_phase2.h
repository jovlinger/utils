/* Draw phase2: whole dirty exteriors + coverage cull (host rect list). */
#ifndef SPINME_TA_DRAW_PHASE2_H
#define SPINME_TA_DRAW_PHASE2_H

#include "ta_draw_update.h"

#include <stddef.h>
#include <stdint.h>

typedef struct ta_rect {
    int x, y, w, h;
} ta_rect_t;

typedef struct ta_phase2_push {
    ta_rect_t exterior;
    unsigned shape_idx;
} ta_phase2_push_t;

/*
 * Nearest->farthest: for each dirty UILayout, if exterior not fully inside
 * union(covered), append push and clear shape+uilayout dirty.
 * Returns number of pushes written (<= out_cap), or -1 on error.
 */
int ta_draw_phase2(ta_draw_scene_t *scene, ta_phase2_push_t *out,
                   size_t out_cap);

#endif
