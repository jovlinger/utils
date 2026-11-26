#include "ta_uilayout.h"

#include <string.h>

ta_pack66_t ta_pack66_rgba(uint8_t r6, uint8_t g6, uint8_t b6, uint8_t a2) {
    /* a2==0 and rgb==0 => TA_PACK66_TRANSPARENT. Nonzero rgb+a2==0 is
     * clamped-additive (ta_sd_blend); holes must use TA_PACK66_TRANSPARENT. */
    if ((a2 & 0x3) == 0 && (r6 & 0x3f) == 0 && (g6 & 0x3f) == 0 &&
        (b6 & 0x3f) == 0) {
        return TA_PACK66_TRANSPARENT;
    }
    return ((ta_pack66_t)(r6 & 0x3f)) | ((ta_pack66_t)(g6 & 0x3f) << 8) |
           ((ta_pack66_t)(b6 & 0x3f) << 16) |
           ((ta_pack66_t)(a2 & 0x3) << TA_PACK66_A2_SHIFT);
}

void ta_unpack66(ta_pack66_t px, uint8_t *r6, uint8_t *g6, uint8_t *b6,
                 uint8_t *a2) {
    uint8_t a = (uint8_t)((px >> TA_PACK66_A2_SHIFT) & 0x3u);

    if (a == 0) {
        if (r6) {
            *r6 = 0;
        }
        if (g6) {
            *g6 = 0;
        }
        if (b6) {
            *b6 = 0;
        }
        if (a2) {
            *a2 = 0;
        }
        return;
    }
    if (r6) {
        *r6 = (uint8_t)(px & 0x3f);
    }
    if (g6) {
        *g6 = (uint8_t)((px >> 8) & 0x3f);
    }
    if (b6) {
        *b6 = (uint8_t)((px >> 16) & 0x3f);
    }
    if (a2) {
        *a2 = a;
    }
}

ta_uilayout_t ta_uilo_make(int dirty, int x, int y, unsigned shape) {
    ta_uilayout_t w = 0;

    if (dirty) {
        w |= 1u << TA_UILO_DIRTY_SHIFT;
    }
    w |= ((ta_uilayout_t)(x & (int)TA_UILO_FIELD_MASK)) << TA_UILO_X_SHIFT;
    w |= ((ta_uilayout_t)(y & (int)TA_UILO_FIELD_MASK)) << TA_UILO_Y_SHIFT;
    w |= ((ta_uilayout_t)(shape & TA_UILO_FIELD_MASK)) << TA_UILO_SHAPE_SHIFT;
    return w;
}

int ta_uilo_dirty(ta_uilayout_t w) {
    return (int)((w >> TA_UILO_DIRTY_SHIFT) & 1u);
}

int ta_uilo_x(ta_uilayout_t w) {
    return (int)((w >> TA_UILO_X_SHIFT) & TA_UILO_FIELD_MASK);
}

int ta_uilo_y(ta_uilayout_t w) {
    return (int)((w >> TA_UILO_Y_SHIFT) & TA_UILO_FIELD_MASK);
}

unsigned ta_uilo_shape(ta_uilayout_t w) {
    return (unsigned)((w >> TA_UILO_SHAPE_SHIFT) & TA_UILO_FIELD_MASK);
}

ta_uilayout_t ta_uilo_set_dirty(ta_uilayout_t w, int dirty) {
    if (dirty) {
        return w | (1u << TA_UILO_DIRTY_SHIFT);
    }
    return w & ~(1u << TA_UILO_DIRTY_SHIFT);
}

static ta_shape_bitmap_t *g_shapes[TA_SHAPE_MAX];

void ta_shape_table_reset(void) {
    memset(g_shapes, 0, sizeof(g_shapes));
}

int ta_shape_table_set(unsigned idx, ta_shape_bitmap_t *shape) {
    if (idx >= TA_SHAPE_MAX) {
        return -1;
    }
    g_shapes[idx] = shape;
    return 0;
}

ta_shape_bitmap_t *ta_shape_table_get(unsigned idx) {
    if (idx >= TA_SHAPE_MAX) {
        return NULL;
    }
    return g_shapes[idx];
}
