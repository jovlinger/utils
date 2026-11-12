#include "ta_stack_compose.h"

#include "ta_draw_phase1.h"

#include <string.h>

static void blit_base_crop(ta_pack66_t *dst, uint16_t ew, uint16_t eh, int ex,
                           int ey, const ta_shape_bitmap_t *base, int base_x,
                           int base_y) {
    uint16_t y;
    uint16_t x;

    if (base == NULL || base->pixels == NULL) {
        return;
    }
    for (y = 0; y < eh; y++) {
        int sy = ey + (int)y - base_y;

        if (sy < 0 || sy >= (int)base->h) {
            continue;
        }
        for (x = 0; x < ew; x++) {
            int sx = ex + (int)x - base_x;

            if (sx < 0 || sx >= (int)base->w) {
                continue;
            }
            dst[(size_t)y * ew + x] =
                base->pixels[(size_t)sy * base->w + (size_t)sx];
        }
    }
}

int ta_stack_compose_exterior(ta_pack66_t *dst, uint16_t ew, uint16_t eh,
                              int ex, int ey, const ta_shape_bitmap_t *base,
                              int base_x, int base_y, const ta_uilayout_t *uilo,
                              size_t n_uilo, size_t top_slot,
                              const ta_shape_bitmap_t *top) {
    size_t i;

    if (dst == NULL || ew == 0 || eh == 0) {
        return -1;
    }
    if (uilo == NULL && n_uilo != 0) {
        return -1;
    }
    memset(dst, 0, (size_t)ew * (size_t)eh * sizeof(ta_pack66_t));
    blit_base_crop(dst, ew, eh, ex, ey, base, base_x, base_y);

    if (top_slot > n_uilo) {
        top_slot = n_uilo;
    }
    for (i = 0; i < top_slot; i++) {
        ta_shape_bitmap_t *hdr;
        int ox;
        int oy;

        /* Skip the follow BASE slot: already cropped from base above. */
        if (i == 0) {
            continue;
        }
        hdr = ta_shape_table_get(ta_uilo_shape(uilo[i]));
        if (hdr == NULL || hdr->pixels == NULL) {
            continue;
        }
        ox = ta_uilo_x(uilo[i]) - ex;
        oy = ta_uilo_y(uilo[i]) - ey;
        ta_draw_blit_bitmap(dst, ew, eh, ox, oy, hdr);
    }
    if (top != NULL && top->pixels != NULL) {
        ta_draw_blit_bitmap(dst, ew, eh, 0, 0, top);
    }
    return 0;
}
