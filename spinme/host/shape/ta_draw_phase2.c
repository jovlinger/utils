#include "ta_draw_phase2.h"

#include <string.h>

static int rect_contains(const ta_rect_t *outer, const ta_rect_t *inner) {
    return inner->x >= outer->x && inner->y >= outer->y &&
           inner->x + inner->w <= outer->x + outer->w &&
           inner->y + inner->h <= outer->y + outer->h;
}

static int fully_covered(const ta_rect_t *covered, size_t n,
                         const ta_rect_t *r) {
    size_t i;

    for (i = 0; i < n; i++) {
        if (rect_contains(&covered[i], r)) {
            return 1;
        }
    }
    return 0;
}

int ta_draw_phase2(ta_draw_scene_t *scene, ta_phase2_push_t *out,
                   size_t out_cap) {
    size_t i;
    size_t npush = 0;
    ta_rect_t covered[64];
    size_t ncov = 0;

    if (scene == NULL || (out_cap > 0 && out == NULL)) {
        return -1;
    }
    /* Nearest (last) -> farthest (0). */
    for (i = scene->n_uilo; i > 0; i--) {
        size_t idx = i - 1;
        ta_uilayout_t w = scene->uilo[idx];
        unsigned sidx;
        ta_shape_bitmap_t *hdr;
        ta_rect_t ext;

        if (!ta_uilo_dirty(w)) {
            continue;
        }
        sidx = ta_uilo_shape(w);
        hdr = ta_shape_table_get(sidx);
        if (hdr == NULL || !hdr->dirty) {
            continue;
        }
        ext.x = ta_uilo_x(w);
        ext.y = ta_uilo_y(w);
        ext.w = (int)hdr->w;
        ext.h = (int)hdr->h;
        if (hdr->tag == TA_SHAPE_TAG_L2R) {
            ta_shape_l2r_t *l2r = (ta_shape_l2r_t *)(void *)hdr;
            ext.w = (int)l2r->w;
            ext.h = (int)l2r->h;
        }
        if (fully_covered(covered, ncov, &ext)) {
            continue;
        }
        if (npush >= out_cap || ncov >= 64) {
            return -1;
        }
        out[npush].exterior = ext;
        out[npush].shape_idx = sidx;
        npush++;
        covered[ncov++] = ext;
        hdr->dirty = 0;
        scene->uilo[idx] = ta_uilo_set_dirty(w, 0);
    }
    return (int)npush;
}
