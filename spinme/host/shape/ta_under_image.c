#include "ta_under_image.h"

#include <string.h>

void ta_under_reset(ta_under_cache_t *u) {
    if (u != NULL) {
        memset(u, 0, sizeof(*u));
    }
}

int ta_under_after_update(ta_under_cache_t *u, ta_draw_scene_t *scene,
                          unsigned overlay_shape_idx, int overlay_box_moved) {
    ta_shape_bitmap_t *base;
    ta_shape_bitmap_t *under;
    ta_shape_bitmap_t *overlay;

    if (u == NULL || scene == NULL || u->under_shape_idx == 0 ||
        u->base_shape_idx == 0) {
        return -1;
    }
    base = ta_shape_table_get(u->base_shape_idx);
    under = ta_shape_table_get(u->under_shape_idx);
    overlay = ta_shape_table_get(overlay_shape_idx);
    if (base == NULL || under == NULL) {
        return -1;
    }

    if (base->dirty) {
        under->dirty = 1;
        u->under_valid = 0;
        return 1;
    }
    if (overlay != NULL && overlay->dirty && !overlay_box_moved) {
        /* Scroll/clock tick: overlay dirty only; under-Cache stays. */
        return 0;
    }
    if (overlay_box_moved) {
        under->dirty = 1;
        u->under_valid = 0;
        return 1;
    }
    return u->under_valid ? 0 : 1;
}
