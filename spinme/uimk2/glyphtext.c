#include "glyphtext.h"

#include <string.h>

const GlyphEntry *glyph_find(const GlyphFont *f, uint16_t codepoint) {
  const GlyphEntry *q = NULL;
  for (uint16_t i = 0; i < f->count; i++) {
    if (f->entries[i].codepoint == codepoint) {
      return &f->entries[i];
    }
    if (f->entries[i].codepoint == '?') {
      q = &f->entries[i];
    }
  }
  return q;
}

uint16_t glyph_new(BitmapTable *t, const GlyphFont *f, uint16_t codepoint) {
  const GlyphEntry *e = glyph_find(f, codepoint);
  if (e == NULL) {
    return 0;
  }
  uint16_t idx = bitmap_new(t, BK_GLYPH, e->width, f->h);
  if (idx != 0) {
    t->b[idx].alpha = f->alpha + e->offset;
  }
  return idx;
}

bool line_build(BitmapTable *t, Arena *a, const GlyphFont *f, const char *text,
                int16_t hsep, uint8_t combiner_ink, Line *out) {
  size_t n = strlen(text);
  uint16_t *list = arena_alloc(a, (n + 1) * sizeof(uint16_t));
  LayoutItem *items = arena_alloc(a, (n ? n : 1) * sizeof(LayoutItem));
  uint16_t row = bitmap_new(t, BK_L2R, 0, 0);
  uint16_t cache = bitmap_new(t, BK_RGBA, 0, 0);
  if (list == NULL || items == NULL || row == 0 || cache == 0) {
    return false;
  }
  t->b[row].items = items;
  t->b[row].items_cap = (uint16_t)n;
  t->b[row].hsep = hsep;
  for (size_t i = 0; i < n; i++) {
    uint16_t g = glyph_new(t, f, (uint8_t)text[i]);
    if (g == 0) {
      return false;
    }
    t->b[g].combiner = combiner_ink;
    bitmap_add(t, row, g, 0, 0);
    list[i] = g;
  }
  list[n] = 0;
  bitmap_pack(t, row);
  uint16_t w = t->b[row].w;
  uint16_t h = f->h;
  Px *px = arena_alloc(a, (size_t)w * h * sizeof(Px));
  if (px == NULL) {
    return false;
  }
  t->b[cache].w = w;
  t->b[cache].h = h;
  t->b[cache].pixels = px;
  bitmap_set_child(t, cache, row);
  out->cache = cache;
  out->row = row;
  out->idxlist = list;
  return true;
}
