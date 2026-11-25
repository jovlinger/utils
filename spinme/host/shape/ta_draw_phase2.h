/* Draw phase2: k-way merge of per-shape W-ordered RLC ranges (top-down). */
#ifndef SPINME_TA_DRAW_PHASE2_H
#define SPINME_TA_DRAW_PHASE2_H

#include "ta_draw_update.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef struct ta_rect {
    int x, y, w, h;
} ta_rect_t;

typedef struct ta_phase2_push {
    ta_rect_t exterior;
    unsigned shape_idx;
} ta_phase2_push_t;

/* Absolute h=1 raster fragment from the merge. */
typedef struct ta_phase2_frag {
    int x, y, w;
    unsigned shape_idx;
} ta_phase2_frag_t;

typedef void (*ta_phase2_frag_fn)(const ta_phase2_frag_t *frag, void *ctx);

/*
 * Merge-sort model: one cursor per dirty shape, each walking its local
 * left-to-right RLC ranges top-down. Emits fragments in global (y,x) order.
 * Overlap across shapes is allowed (no clip). Clears shape+uilayout dirty.
 * Returns 0, or -1 on error.
 */
int ta_draw_phase2_foreach_frag(ta_draw_scene_t *scene, ta_phase2_frag_fn fn,
                                void *ctx);

/*
 * Same merge; records each shape's exterior once, in first-fragment order
 * (top-down appearance). Returns number of exteriors (<= out_cap), or -1.
 */
int ta_draw_phase2(ta_draw_scene_t *scene, ta_phase2_push_t *out,
                   size_t out_cap);

#ifdef __cplusplus
}
#endif
#endif
