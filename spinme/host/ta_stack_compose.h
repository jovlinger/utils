/* Pixel-accurate glass stack compose for one exterior rect.
 *
 * Farthest -> nearest: base crop, then follow slots [0, top_slot), then an
 * optional top bitmap (chrome icon) at (0,0) in exterior space. Every layer
 * is pack66 src-over (a2).
 */
#ifndef SPINME_TA_STACK_COMPOSE_H
#define SPINME_TA_STACK_COMPOSE_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Compose into dst[ew*eh]. Returns 0 on success, -1 on bad args.
 * top_slot is an exclusive upper bound on follow indices under the optional
 * top overlay (pass TA_FOLLOW_TRANSPORT then the transport icon as top).
 */
int ta_stack_compose_exterior(ta_pack66_t *dst, uint16_t ew, uint16_t eh,
                              int ex, int ey, const ta_shape_bitmap_t *base,
                              int base_x, int base_y, const ta_uilayout_t *uilo,
                              size_t n_uilo, size_t top_slot,
                              const ta_shape_bitmap_t *top);

#ifdef __cplusplus
}
#endif

#endif
