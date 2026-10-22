/*
 * Glyph nodes and text lines for the uimk2 follow view.
 *
 * A glyph node reads its alpha from the generated flash table (glyphs_gen.h).
 * It allocates no pixels. A line is a zero-terminated IdxList of glyph
 * indexes plus one RGBA cache, both bump-allocated from the arena.
 * The line's ink color (SET-RGB combiner) is not applied yet.
 */
#ifndef UIMK2_GLYPH_H
#define UIMK2_GLYPH_H

#include <stdint.h>

#include "arena.h"
#include "bitmap.h"

typedef struct {
    uint16_t *idx;  /* glyph node indexes, zero-terminated, in the arena */
    uint16_t cache; /* RGBA node sized to the line, owns the pixels */
} GlyphLine;

/* Glyph node for codepoint cp. A codepoint with no glyph uses '?'.
 * Returns BM_NULL when the bitmap table is full. */
uint16_t glyph_new(BitmapTable *t, uint16_t cp);

/* Builds a line with one glyph per byte of text and hsep pixels between
 * glyphs. The cache is painted over paper. Returns 1 on success, 0 when the
 * arena or the bitmap table is full. */
int glyph_line(Arena *a, BitmapTable *t, const char *text, uint16_t hsep,
               const uint8_t paper[3], GlyphLine *out);

#endif
