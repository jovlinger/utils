#include "ta_viewport.h"

#include <string.h>

int ta_viewport_bake(ta_shape_viewport_t *vp) {
    ta_shape_bitmap_t *child;
    uint16_t y;
    uint16_t x;

    if (vp == NULL || vp->tag != TA_SHAPE_TAG_VIEWPORT || vp->pixels == NULL) {
        return -1;
    }
    child = ta_shape_table_get(vp->child_idx);
    if (child == NULL || child->pixels == NULL) {
        return -1;
    }
    memset(vp->pixels, 0,
           (size_t)vp->w * (size_t)vp->h * sizeof(ta_pack66_t));
    for (y = 0; y < vp->h; y++) {
        int sy = (int)y + (int)vp->oy;
        if (sy < 0 || sy >= (int)child->h) {
            continue;
        }
        for (x = 0; x < vp->w; x++) {
            int sx = (int)x + (int)vp->ox;
            ta_pack66_t px;
            uint8_t a;

            if (sx < 0 || sx >= (int)child->w) {
                continue;
            }
            px = child->pixels[(size_t)sy * child->w + (size_t)sx];
            a = (uint8_t)((px >> TA_PACK66_A2_SHIFT) & 3u);
            if (a == 0) {
                continue;
            }
            vp->pixels[(size_t)y * vp->w + x] = px;
        }
    }
    vp->dirty = 1;
    return 0;
}
