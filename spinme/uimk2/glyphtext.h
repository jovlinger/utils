/* Glyph nodes over the flash font table, and text lines built in the arena.
 * See spinme/uimk2.txt. A Glyph node points into read-only flash alpha bytes
 * and allocates no pixel buffer. A line is an IdxList of glyph indexes, an
 * L2R layout, and one RGBA cache, all bump-allocated in the dynamic region. */
#ifndef UIMK2_GLYPHTEXT_H
#define UIMK2_GLYPHTEXT_H

#include <stdbool.h>
#include <stdint.h>

#include "arena.h"
#include "bitmap.h"

/* Same layout as the entries emitted by genglyphs.py. */
typedef struct {
  uint16_t codepoint;
  uint8_t width;
  uint32_t offset;
} GlyphEntry;

typedef struct {
  const GlyphEntry *entries; /* sorted by codepoint */
  uint16_t count;
  const uint8_t *alpha;      /* flash blob; entry bytes at offset, width*h */
  uint16_t h;                /* H: height of every glyph box */
  uint16_t b;                /* B: baseline row of every glyph box */
} GlyphFont;

/* Entry for codepoint, else the entry for '?', else NULL. */
const GlyphEntry *glyph_find(const GlyphFont *f, uint16_t codepoint);

/* New Glyph node: w = entry width, h = font H, alpha points into flash.
 * Returns 0 when the table is full or the font has no '?'. */
uint16_t glyph_new(BitmapTable *t, const GlyphFont *f, uint16_t codepoint);

typedef struct {
  uint16_t cache;     /* RGBA node owning the line's pixels */
  uint16_t row;       /* L2R node holding the glyphs */
  uint16_t *idxlist;  /* zero-terminated glyph indexes, in the arena */
} Line;

/* Build a line for text (ASCII, one byte per codepoint). The IdxList, the
 * LayoutItems, and the cache pixels come from the arena; glyph and layout
 * headers come from the table. ink selects the SET-RGB combiner that tints
 * the glyphs; combiner_ink is that combiner's table index (0 = no tint).
 * Returns false when the arena or the table is full; allocations already
 * made stay for the caller's rewind. */
bool line_build(BitmapTable *t, Arena *a, const GlyphFont *f, const char *text,
                int16_t hsep, uint8_t combiner_ink, Line *out);

#endif
