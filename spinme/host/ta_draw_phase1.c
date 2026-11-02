#include "ta_draw_phase1.h"

#include "ta_shape_l2r.h"

#include <string.h>

static void blit_bitmap(ta_pack66_t *dst, uint16_t dst_w, uint16_t dst_h,
                        int ox, int oy, const ta_shape_bitmap_t *src) {
    uint16_t y;
    uint16_t x;

    if (dst == NULL || src == NULL || src->pixels == NULL) {
        return;
    }
    for (y = 0; y < src->h; y++) {
        int dy = oy + (int)y;
        if (dy < 0 || dy >= (int)dst_h) {
            continue;
        }
        for (x = 0; x < src->w; x++) {
            int dx = ox + (int)x;
            ta_pack66_t px;
            uint8_t a;

            if (dx < 0 || dx >= (int)dst_w) {
                continue;
            }
            px = src->pixels[(size_t)y * src->w + x];
            a = (uint8_t)((px >> TA_PACK66_A2_SHIFT) & 3u);
            if (a == 0) {
                continue;
            }
            dst[(size_t)dy * dst_w + (size_t)dx] = px;
        }
    }
}

static int rebuild_l2r(ta_shape_l2r_t *l2r, const ta_shape_bitmap_t *under) {
    size_t wi;
    unsigned tmp[8];
    int ox = 0;
    size_t item = 0;

    if (l2r->pixels == NULL || l2r->w == 0 || l2r->h == 0) {
        return -1;
    }
    memset(l2r->pixels, 0, (size_t)l2r->w * (size_t)l2r->h * sizeof(ta_pack66_t));
    if (under != NULL) {
        blit_bitmap(l2r->pixels, l2r->w, l2r->h, 0, 0, under);
    }
    wi = 0;
    for (;;) {
        size_t got;
        size_t i;

        got = ta_shapepack_decode_word(l2r->pack[wi], tmp, 8);
        if (got == 0) {
            break;
        }
        for (i = 0; i < got; i++) {
            ta_shape_bitmap_t *ch;
            int kern = 0;

            if (tmp[i] == 0) {
                continue;
            }
            ch = ta_shape_table_get(tmp[i]);
            if (ch == NULL || ch->tag != TA_SHAPE_TAG_BITMAP) {
                return -1;
            }
            blit_bitmap(l2r->pixels, l2r->w, l2r->h, ox, 0, ch);
            ox += (int)ch->w;
            if (l2r->kernings != NULL && item < l2r->n_items) {
                kern = (int)l2r->kernings[item];
            }
            ox += kern;
            item++;
        }
        wi++;
    }
    return 0;
}

int ta_draw_phase1(ta_draw_scene_t *scene, const ta_phase1_opts_t *opts) {
    size_t i;
    unsigned under_idx = 0;
    ta_shape_bitmap_t *under = NULL;

    if (scene == NULL) {
        return -1;
    }
    if (opts != NULL) {
        under_idx = opts->under_shape_idx;
        if (under_idx != 0) {
            under = ta_shape_table_get(under_idx);
        }
    }
    /* Farthest (0) -> nearest (n-1). */
    for (i = 0; i < scene->n_uilo; i++) {
        unsigned sidx = ta_uilo_shape(scene->uilo[i]);
        ta_shape_bitmap_t *hdr = ta_shape_table_get(sidx);

        if (hdr == NULL || !hdr->dirty) {
            continue;
        }
        if (hdr->tag == TA_SHAPE_TAG_BITMAP) {
            /* Already has pixels; nothing to bake. */
            continue;
        }
        if (hdr->tag == TA_SHAPE_TAG_L2R) {
            ta_shape_l2r_t *l2r = (ta_shape_l2r_t *)(void *)hdr;
            if (rebuild_l2r(l2r, under) != 0) {
                return -1;
            }
        }
    }
    return 0;
}
