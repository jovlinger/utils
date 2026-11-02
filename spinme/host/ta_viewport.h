/* Viewport Shape: intersect child with window; ox/oy scroll (title only). */
#ifndef SPINME_TA_VIEWPORT_H
#define SPINME_TA_VIEWPORT_H

#include "ta_uilayout.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
enum {
    TA_SHAPE_TAG_VIEWPORT = 3
};

typedef struct ta_shape_viewport {
    uint8_t tag;
    uint8_t dirty;
    uint16_t w; /* window width */
    uint16_t h;
    ta_pack66_t *pixels; /* window-sized bake target */
    unsigned child_idx;  /* ShapeBitMap / L2R content */
    int16_t ox;
    int16_t oy;
} ta_shape_viewport_t;

/* Bake visible intersection of child into viewport pixels at ox/oy.
 * Does not touch under-image shapes. */
int ta_viewport_bake(ta_shape_viewport_t *vp);

#ifdef __cplusplus
}
#endif
#endif
