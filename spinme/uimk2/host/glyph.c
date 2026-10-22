#include <string.h>

#include "glyph.h"
#include "glyphs_gen.h"

#define N_GLYPHS ((size_t)(sizeof glyph_table / sizeof glyph_table[0]))

static const GlyphEntry *lookup(uint16_t cp)
{
    size_t i;

    for (i = 0; i < N_GLYPHS; i++) {
        if (glyph_table[i].cp == cp) {
            return &glyph_table[i];
        }
    }
    for (i = 0; i < N_GLYPHS; i++) {
        if (glyph_table[i].cp == GLYPH_FALLBACK) {
            return &glyph_table[i];
        }
    }
    return NULL;
}

uint16_t glyph_new(BitmapTable *t, uint16_t cp)
{
    const GlyphEntry *e = lookup(cp);

    if (e == NULL) {
        return BM_NULL;
    }
    return bm_new_glyph(t, glyph_alpha + e->offset, e->width, GLYPH_HEIGHT);
}

int glyph_line(Arena *a, BitmapTable *t, const char *text, uint16_t hsep,
               const uint8_t paper[3], GlyphLine *out)
{
    size_t n = strlen(text);
    uint16_t *list;
    size_t i, w = 0;
    uint8_t *px;

    list = arena_alloc(a, (n + 1) * sizeof *list);
    if (list == NULL) {
        return 0;
    }
    for (i = 0; i < n; i++) {
        uint16_t g = glyph_new(t, (unsigned char)text[i]);
        if (g == BM_NULL) {
            return 0;
        }
        list[i] = g;
        w += t->nodes[g].w;
    }
    list[n] = BM_NULL;
    if (n > 0) {
        w += (size_t)hsep * (n - 1);
    }
    px = arena_alloc(a, w * GLYPH_HEIGHT * 4u);
    if (px == NULL) {
        return 0;
    }
    out->cache = bm_new(t, BM_KIND_RGBA, (uint16_t)w, GLYPH_HEIGHT);
    if (out->cache == BM_NULL) {
        return 0;
    }
    bm_set_owner(t, out->cache, px, paper);
    out->idx = list;
    return 1;
}
