#include "ta_draw_update.h"

#include <string.h>

static void mark_dirty(ta_draw_scene_t *scene, unsigned shape_idx) {
    size_t i;
    ta_shape_bitmap_t *hdr;

    hdr = ta_shape_table_get(shape_idx);
    if (hdr != NULL) {
        hdr->dirty = 1;
    }
    for (i = 0; i < scene->n_uilo; i++) {
        if (ta_uilo_shape(scene->uilo[i]) == shape_idx) {
            scene->uilo[i] = ta_uilo_set_dirty(scene->uilo[i], 1);
        }
    }
}

static void propagate_shadow(ta_draw_scene_t *scene, const ta_draw_node_t *n) {
    size_t i;

    for (i = 0; i < n->shadow_n; i++) {
        mark_dirty(scene, n->shadow_higher[i]);
    }
}

static int update_represent_time(ta_draw_scene_t *scene, ta_draw_node_t *n) {
    ta_shape_l2r_t *l2r;
    unsigned idxs[16];
    size_t nidx = 0;
    size_t i;
    size_t nw = 0;
    char ch;
    ta_pack66_t *keep_px;

    l2r = (ta_shape_l2r_t *)(void *)ta_shape_table_get(n->shape_idx);
    if (l2r == NULL || l2r->tag != TA_SHAPE_TAG_L2R || l2r->pack == NULL) {
        return -1;
    }
    for (i = 0; scene->clock_hhmmss[i] != '\0' && nidx < 16; i++) {
        ch = scene->clock_hhmmss[i];
        if (ch >= '0' && ch <= '9') {
            unsigned g = scene->digit_glyph[(unsigned)(ch - '0')];
            if (g == 0) {
                return -1;
            }
            idxs[nidx++] = g;
        } else if (ch == ':') {
            unsigned g = scene->colon_glyph != 0 ? scene->colon_glyph
                                                 : scene->digit_glyph[0];
            if (g == 0) {
                return -1;
            }
            idxs[nidx++] = g;
        } else {
            return -1;
        }
    }
    keep_px = l2r->pixels;
    if (ta_shapepack_encode((uint32_t *)(void *)l2r->pack, 8, &nw, idxs, nidx,
                            TA_PACK_TAG_4x7) != 0) {
        return -1;
    }
    l2r->n_items = nidx;
    l2r->kernings = NULL;
    if (ta_shape_l2r_compute_size(l2r) != 0) {
        return -1;
    }
    l2r->pixels = keep_px; /* defs only -- pixmap pointer/bytes untouched */

    mark_dirty(scene, n->shape_idx);
    propagate_shadow(scene, n);
    return 0;
}

int ta_draw_update(ta_draw_scene_t *scene) {
    size_t i;

    if (scene == NULL) {
        return -1;
    }
    for (i = 0; i < scene->n_nodes; i++) {
        ta_draw_node_t *n = &scene->nodes[i];

        switch (n->update_enum) {
        case TA_UPD_NOOP:
            break;
        case TA_UPD_REPRESENT_TIME:
            if (update_represent_time(scene, n) != 0) {
                return -1;
            }
            break;
        default:
            return -1;
        }
    }
    return 0;
}
