/* ShapeL2R + shapepack (idx packing tags 11/10/01/00). */
#ifndef SPINME_TA_SHAPE_L2R_H
#define SPINME_TA_SHAPE_L2R_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

enum {
    TA_SHAPE_TAG_L2R = 2
};

/* Word tag in top 2 bits: packing density. */
enum {
    TA_PACK_TAG_3x10 = 3, /* 11: three 10-bit idxs */
    TA_PACK_TAG_4x7 = 2,  /* 10: four 7-bit idxs */
    TA_PACK_TAG_5x6 = 1,  /* 01: five 6-bit idxs */
    TA_PACK_TAG_6x5 = 0   /* 00: six 5-bit idxs */
};

#define TA_SHAPEPACK_END 0u /* zero idx terminator in unpacked stream */

typedef struct ta_shape_l2r {
    uint8_t tag; /* TA_SHAPE_TAG_L2R */
    uint8_t dirty;
    uint16_t w;
    uint16_t h;
    ta_pack66_t *pixels; /* optional bake target; may be NULL until phase1 */
    const uint32_t *pack; /* zero-terminated pack words (last word may pad) */
    const int8_t *kernings; /* signed 4-bit stored as int8 per item */
    size_t n_items;         /* unpacked item count (excl terminator) */
} ta_shape_l2r_t;

/* Pack idxs into words with chosen tag; writes *out_n words; -1 on overflow. */
int ta_shapepack_encode(uint32_t *out, size_t out_cap, size_t *out_n,
                        const unsigned *idxs, size_t n, int tag);

/* Decode one pack word; returns count of idxs written (0 if empty/end). */
size_t ta_shapepack_decode_word(uint32_t word, unsigned *idxs, size_t max);

/* Compute w/h from child bitmaps + kernings; sets l2r->w/h. */
int ta_shape_l2r_compute_size(ta_shape_l2r_t *l2r);

#endif
