#include "glyph.h"

#include <stddef.h>
#include <string.h>

const GlyphEntry *glyph_find(const GlyphFont *f, uint16_t codepoint) {
  const GlyphEntry *q = NULL;
  for (int i = 0; i < f->count; i++) {
    if (f->table[i].codepoint == codepoint) return &f->table[i];
    if (f->table[i].codepoint == '?') q = &f->table[i];
  }
  return q;
}

int glyph_init(BitmapTable *t, uint16_t idx, uint16_t parent,
               const GlyphFont *f, uint16_t codepoint) {
  const GlyphEntry *e = glyph_find(f, codepoint);
  Bitmap *b = &t->b[idx];
  if (!e) return -1;
  memset(b, 0, sizeof *b);
  b->kind = BM_GLYPH;
  b->parent = parent;
  b->w = e->width;
  b->h = f->h;
  b->alpha = f->alpha + e->offset;
  b->codepoint = e->codepoint;
  return 0;
}

int text_line_build(Arena *a, BitmapTable *t, const GlyphFont *f,
                    uint16_t cache_idx, uint16_t l2r_idx, uint16_t first_idx,
                    uint16_t parent, const char *text, int32_t hsep,
                    uint16_t combiner) {
  size_t n = strlen(text);
  uint16_t *list = arena_alloc(a, (n + 1) * sizeof(uint16_t), ARENA_DYN);
  if (!list) return -1;
  for (size_t i = 0; i < n; i++) {
    uint16_t gi = (uint16_t)(first_idx + i);
    if (gi >= t->n || glyph_init(t, gi, l2r_idx, f, (uint8_t)text[i]) != 0)
      return -1;
    list[i] = gi;
  }
  list[n] = 0;

  Bitmap *l = &t->b[l2r_idx];
  memset(l, 0, sizeof *l);
  l->kind = BM_L2R;
  l->parent = cache_idx;
  l->list = list;
  l->sep = hsep;
  l->combiner = combiner;
  bm_measure(t, l2r_idx);

  size_t bytes = (size_t)l->w * (size_t)l->h * 4;
  uint8_t *pix = arena_alloc(a, bytes, ARENA_DYN);
  if (!pix) return -1;
  memset(pix, 0, bytes);

  Bitmap *c = &t->b[cache_idx];
  memset(c, 0, sizeof *c);
  c->kind = BM_RGBA;
  c->parent = parent;
  c->w = l->w;
  c->h = l->h;
  c->pix = pix;
  c->child = l2r_idx; /* paper stays (0,0,0,0): transparent */
  return 0;
}
