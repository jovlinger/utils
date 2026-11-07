#include "ta_draw_phase1.h"

#include "ta_shape_l2r.h"
#include "ta_shape_swap.h"
#include "ta_viewport.h"

#include <string.h>

void ta_draw_blit_bitmap(ta_pack66_t *dst, uint16_t dst_w, uint16_t dst_h,
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

/* Copy the base crop that sits under exterior (ex,ey,w,h) into dst. */
static void blit_base_crop(ta_pack66_t *dst, uint16_t w, uint16_t h, int ex,
                           int ey, const ta_shape_bitmap_t *base, int base_x,
                           int base_y) {
    uint16_t y;
    uint16_t x;

    if (base == NULL || base->pixels == NULL) {
        return;
    }
    for (y = 0; y < h; y++) {
        int sy = ey + (int)y - base_y;
        if (sy < 0 || sy >= (int)base->h) {
            continue;
        }
        for (x = 0; x < w; x++) {
            int sx = ex + (int)x - base_x;
            if (sx < 0 || sx >= (int)base->w) {
                continue;
            }
            dst[(size_t)y * w + x] =
                base->pixels[(size_t)sy * base->w + (size_t)sx];
        }
    }
}

/* Clear, base crop (optional), under (optional), then children L->R. */
static int rebuild_l2r(ta_shape_l2r_t *l2r, const ta_shape_bitmap_t *under,
                       int ex, int ey, const ta_shape_bitmap_t *base,
                       int base_x, int base_y) {
    size_t wi;
    unsigned tmp[8];
    int ox = 0;
    size_t item = 0;

    if (l2r->pixels == NULL || l2r->w == 0 || l2r->h == 0) {
        return -1;
    }
    memset(l2r->pixels, 0, (size_t)l2r->w * (size_t)l2r->h * sizeof(ta_pack66_t));
    if (base != NULL) {
        blit_base_crop(l2r->pixels, l2r->w, l2r->h, ex, ey, base, base_x,
                       base_y);
    }
    if (under != NULL) {
        ta_draw_blit_bitmap(l2r->pixels, l2r->w, l2r->h, 0, 0, under);
    }
    if (l2r->pack == NULL) {
        return 0;
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
            ta_draw_blit_bitmap(l2r->pixels, l2r->w, l2r->h, ox, 0, ch);
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

/* Viewport: window = base crop + child at -ox (+ wrapped copy). */
static int bake_viewport(ta_shape_viewport_t *vp, int ex, int ey,
                         const ta_shape_bitmap_t *base, int base_x,
                         int base_y) {
    ta_shape_bitmap_t *child;
    int ox;

    if (vp->pixels == NULL || vp->w == 0 || vp->h == 0) {
        return -1;
    }
    child = ta_shape_table_get(vp->child_idx);
    if (child == NULL) {
        return -1;
    }
    if (child->dirty && child->tag == TA_SHAPE_TAG_L2R) {
        /* Child keeps transparent paper; the window supplies the base. */
        if (rebuild_l2r((ta_shape_l2r_t *)(void *)child, NULL, 0, 0, NULL, 0,
                        0) != 0) {
            return -1;
        }
        child->dirty = 0;
    }
    memset(vp->pixels, 0, (size_t)vp->w * (size_t)vp->h * sizeof(ta_pack66_t));
    blit_base_crop(vp->pixels, vp->w, vp->h, ex, ey, base, base_x, base_y);
    if (child->pixels == NULL) {
        return 0;
    }
    ox = (int)vp->ox;
    if (child->w > vp->w) {
        int period = (int)child->w + TA_PHASE1_SCROLL_GAP;
        ox %= period;
        if (ox < 0) {
            ox += period;
        }
        ta_draw_blit_bitmap(vp->pixels, vp->w, vp->h, -ox, -(int)vp->oy, child);
        ta_draw_blit_bitmap(vp->pixels, vp->w, vp->h, period - ox,
                            -(int)vp->oy, child);
    } else {
        ta_draw_blit_bitmap(vp->pixels, vp->w, vp->h, 0, -(int)vp->oy, child);
    }
    return 0;
}

int ta_draw_phase1(ta_draw_scene_t *scene, const ta_phase1_opts_t *opts) {
    size_t i;
    ta_shape_bitmap_t *under = NULL;
    ta_shape_bitmap_t *base = NULL;
    unsigned base_idx = 0;
    int base_x = 0;
    int base_y = 0;

    if (scene == NULL) {
        return -1;
    }
    if (opts != NULL) {
        if (opts->under_shape_idx != 0) {
            under = ta_shape_table_get(opts->under_shape_idx);
        }
        base_idx = opts->base_shape_idx;
        if (base_idx != 0) {
            base = ta_shape_table_get(base_idx);
            base_x = opts->base_x;
            base_y = opts->base_y;
        }
    }
    /* Farthest (0) -> nearest (n-1). */
    for (i = 0; i < scene->n_uilo; i++) {
        ta_uilayout_t w = scene->uilo[i];
        unsigned sidx = ta_uilo_shape(w);
        ta_shape_bitmap_t *hdr = ta_shape_table_get(sidx);

        if (hdr == NULL || !hdr->dirty) {
            continue;
        }
        if (hdr->tag == TA_SHAPE_TAG_BITMAP) {
            /* Already has pixels; nothing to bake. */
            continue;
        }
        if (hdr->tag == TA_SHAPE_TAG_L2R) {
            if (rebuild_l2r((ta_shape_l2r_t *)(void *)hdr, under, ta_uilo_x(w),
                            ta_uilo_y(w), sidx == base_idx ? NULL : base,
                            base_x, base_y) != 0) {
                return -1;
            }
            continue;
        }
        if (hdr->tag == TA_SHAPE_TAG_VIEWPORT) {
            if (bake_viewport((ta_shape_viewport_t *)(void *)hdr, ta_uilo_x(w),
                              ta_uilo_y(w), base, base_x, base_y) != 0) {
                return -1;
            }
            continue;
        }
        if (hdr->tag == TA_SHAPE_TAG_SWAP) {
            /* Alias pixels to the active same-size child. */
            if (ta_shape_swap_bind((ta_shape_swap_t *)(void *)hdr) != 0) {
                return -1;
            }
        }
    }
    return 0;
}
