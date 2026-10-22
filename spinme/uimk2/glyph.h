/* Glyph nodes and text lines for uimk2. A glyph reads its alpha bytes from
 * the flash table written by glyphgen.py and allocates no pixel buffer. See
 * todo 2d255758 (uimk2 bitmap compositor), Bitmap table and What is cached. */
#ifndef UIMK2_GLYPH_H
#define UIMK2_GLYPH_H

#include <stdint.h>

#include "arena.h"
#include "bitmap.h"

typedef struct {
  uint16_t codepoint;
  uint16_t width;
  uint32_t offset;
} GlyphEntry;

typedef struct {
  const GlyphEntry *table;
  int count;
  const uint8_t *alpha; /* flash bytes; entry data is width * h at offset */
  int h;                /* H: same for every glyph */
  int base;             /* B: baseline row, same for every glyph */
} GlyphFont;

/* Entry for a codepoint; '?' when missing; NULL only if '?' is missing too. */
const GlyphEntry *glyph_find(const GlyphFont *f, uint16_t codepoint);

/* Make table[idx] a Glyph node: parent, tight w, h = H, alpha pointing into
 * flash. No pixel buffer. Returns 0, or -1 when no entry (not even '?'). */
int glyph_init(BitmapTable *t, uint16_t idx, uint16_t parent,
               const GlyphFont *f, uint16_t codepoint);

/* Build one text line in the dynamic arena region.
 *   cache_idx  RGBA node owning the line cache (parent = parent)
 *   l2r_idx    L2R node that is the cache's child
 *   first_idx  glyph headers first_idx .. first_idx + strlen(text) - 1
 * The IdxList and the cache pixels come from the arena (ARENA_DYN); glyph
 * headers come from the bitmap table. The L2R node carries combiner, so a
 * SET-RGB entry tints the ink and leaves alpha alone. The cache paper is
 * transparent. Returns 0, or -1 when the arena or text is too small (the
 * caller then resets). */
int text_line_build(Arena *a, BitmapTable *t, const GlyphFont *f,
                    uint16_t cache_idx, uint16_t l2r_idx, uint16_t first_idx,
                    uint16_t parent, const char *text, int32_t hsep,
                    uint16_t combiner);

#endif
