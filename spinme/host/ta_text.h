/* Text constructor: ascii -> ShapeL2R via glyph ShapeBitMaps. */
#ifndef SPINME_TA_TEXT_H
#define SPINME_TA_TEXT_H

#include "ta_shape_l2r.h"

#include <stddef.h>

/* Glyph map: ascii 32..126 -> shape idx; 0 means missing. */
typedef struct ta_glyph_map {
    unsigned idx[95]; /* ascii - 32 */
} ta_glyph_map_t;

void ta_glyph_map_clear(ta_glyph_map_t *m);
int ta_glyph_map_set(ta_glyph_map_t *m, char ch, unsigned shape_idx);

/*
 * Build L2R from ascii. Encodes shapepack into pack_buf; kernings all 0
 * unless kern_table non-NULL (indexed by ascii-32). Fills *out.
 */
int ta_text_build(ta_shape_l2r_t *out, const char *ascii,
                  const ta_glyph_map_t *glyphs, const int8_t *kern_table,
                  uint32_t *pack_buf, size_t pack_cap, int8_t *kern_buf,
                  size_t kern_cap);

#endif
