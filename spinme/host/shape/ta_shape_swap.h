/* SwapShape: n same-size children; display exactly one (active index). */
#ifndef SPINME_TA_SHAPE_SWAP_H
#define SPINME_TA_SHAPE_SWAP_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    TA_SHAPE_TAG_SWAP = 4
};

#define TA_SWAP_MAX 8

typedef struct ta_shape_swap {
    uint8_t tag; /* TA_SHAPE_TAG_SWAP */
    uint8_t dirty;
    uint16_t w;
    uint16_t h;
    ta_pack66_t *pixels; /* aliased to active child's pixels after bind */
    unsigned n;
    unsigned active;
    unsigned child_idx[TA_SWAP_MAX];
} ta_shape_swap_t;

/* Require 1..TA_SWAP_MAX children; all must share identical w/h and have
 * pixels. Sets swap->w/h and aliases pixels to the active child. -1 on bad. */
int ta_shape_swap_bind(ta_shape_swap_t *swap);

/* Change which child is shown; marks dirty and rebinds. -1 if out of range. */
int ta_shape_swap_set_active(ta_shape_swap_t *swap, unsigned active);

/* Active child shape index, or 0 if unbound. */
unsigned ta_shape_swap_active_idx(const ta_shape_swap_t *swap);

#ifdef __cplusplus
}
#endif

#endif
