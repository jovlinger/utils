/* uimk2 glyphs and text lines.
 *
 * A Glyph node reads its coverage straight from the flash font table
 * (uimk2_glyphs.h): w is the glyph's ink width, h is uimk2_glyph_h, and the
 * baseline is row uimk2_glyph_b. It allocates no pixels. A missing
 * codepoint uses '?'.
 *
 * A text line is a Cache. Its foreground is an L2R of one Glyph node per
 * codepoint. Its background is a paper raster of the same size. The IdxList,
 * the paper, and the stored picture are one arena block. The L2R carries
 * the line's combiner, normally SET on RGB to the ink color, so the white
 * glyph ink is tinted before it is baked over the paper. The Cache rebakes
 * only when that node is marked dirty.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_LINE_H
#define UIMK2_LINE_H

#include <stdint.h>

#include "uimk2_arena.h"
#include "uimk2_bitmap.h"
#include "uimk2_glyphs.h"

/* The table entry for cp, or the entry for '?' when cp is missing. NULL
 * only when the table has no '?' either. */
const uimk2_glyph_entry *uimk2_glyph_find(uint32_t cp);

/* A Glyph header for cp reading the flash alpha; 0 when the table is full
 * or the codepoint and '?' are both missing. */
uint16_t uimk2_glyph_new(uimk2_bmtab *t, uint32_t cp);

typedef struct {
    uint16_t cache;      /* Cache: fg over paper, stored pixels */
    uint16_t pack;       /* L2R of the glyphs, child of cache */
    uint16_t first_hdr;  /* first header index this line took */
    uint16_t *idx;       /* the L2R's IdxList, in the arena */
    uint32_t arena_off;  /* arena offset of the line's block */
    uint32_t arena_len;  /* bytes the line took from the arena */
} uimk2_line;

/* Build a line from UTF-8 text: one Glyph per codepoint (an invalid byte
 * is one '?'), packed L2R with hsep, tinted by combiner index comb on the
 * L2R, and baked into a Cache over a paper raster of the L2R's size. The
 * IdxList, the paper, and the store come from one arena alloc. The cache's
 * parent is 0 (the caller places it) and its whole box is marked dirty.
 * Returns false when the arena or the table is full; no headers are kept
 * then, and the arena is unchanged. */
bool uimk2_line_build(uimk2_bmtab *t, uimk2_arena *a, uimk2_line *line,
                      const char *utf8, uint16_t hsep, uint8_t comb,
                      const uint8_t paper[4]);

#endif /* UIMK2_LINE_H */
