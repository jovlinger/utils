/* Host test for Glyph nodes over the flash table and text lines.
 * Build and run: make -C spinme test. Uses the generated glyphs12.h. */
#include <stdio.h>
#include <string.h>

#include "glyphs12.h"
#include "glyphtext.h"

static int failures = 0;
#define CHECK(c)                                          \
  do {                                                    \
    if (!(c)) {                                           \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); \
      failures++;                                         \
    }                                                     \
  } while (0)

static const GlyphFont kFont = {kGlyphTable, GLYPH_COUNT, kGlyphAlpha, GLYPH_H,
                                GLYPH_B};
/* combiner 1: SET rgb = (200, 100, 50), alpha untouched */
static const Combiner kComb[2] = {{0, 0, {0, 0, 0, 0}},
                                  {7, CB_SET, {200, 100, 50, 0}}};

enum { CAP = 128 };

static void test_glyph_node(void) {
  Bitmap store[CAP];
  BitmapTable t;
  bitmap_table_init(&t, store, CAP);
  uint16_t g = glyph_new(&t, &kFont, 'A');
  const GlyphEntry *e = glyph_find(&kFont, 'A');
  CHECK(g != 0 && e != NULL);
  CHECK(t.b[g].kind == BK_GLYPH);
  CHECK(t.b[g].h == GLYPH_H);
  CHECK(t.b[g].w == e->width);
  /* reads flash in place: no copy, no pixel buffer */
  CHECK(t.b[g].alpha == kGlyphAlpha + e->offset);
  CHECK(t.b[g].pixels == NULL);
  /* missing codepoint draws '?' */
  uint16_t m = glyph_new(&t, &kFont, 0x4E2D);
  const GlyphEntry *q = glyph_find(&kFont, '?');
  CHECK(m != 0 && t.b[m].alpha == kGlyphAlpha + q->offset);
  CHECK(t.b[m].w == q->width);
  /* every glyph shares H */
  for (uint16_t i = 0; i < GLYPH_COUNT; i++) {
    uint16_t n = glyph_new(&t, &kFont, kGlyphTable[i].codepoint);
    CHECK(n != 0);
    CHECK(t.b[n].h == GLYPH_H);
  }
}

static void test_line(void) {
  Bitmap store[CAP];
  BitmapTable t;
  static uint32_t mem[8192];
  Arena a;
  Line ln;
  bitmap_table_init(&t, store, CAP);
  t.comb = kComb;
  t.ncomb = 2;
  arena_init(&a, mem, sizeof(mem));
  arena_seal(&a);
  const char *text = "Hi?";
  CHECK(line_build(&t, &a, &kFont, text, 1, 1, &ln));

  /* IdxList is zero-terminated, one glyph index per char */
  CHECK(ln.idxlist[0] != 0 && ln.idxlist[1] != 0 && ln.idxlist[2] != 0);
  CHECK(ln.idxlist[3] == 0);
  uint16_t expect_w = 0;
  for (int i = 0; i < 3; i++) {
    const Bitmap *g = &t.b[ln.idxlist[i]];
    CHECK(g->kind == BK_GLYPH && g->pixels == NULL);
    CHECK(g->parent == ln.row);
    expect_w = (uint16_t)(expect_w + g->w);
  }
  expect_w = (uint16_t)(expect_w + 2); /* two hsep gaps */
  CHECK(t.b[ln.row].w == expect_w);
  CHECK(t.b[ln.row].h == GLYPH_H);
  CHECK(t.b[ln.cache].w == expect_w && t.b[ln.cache].h == GLYPH_H);

  /* arena holds exactly IdxList + LayoutItems + one cache, no per-glyph pixels */
  size_t want = ((4 * sizeof(uint16_t) + 3) & ~(size_t)3) +
                ((3 * sizeof(LayoutItem) + 3) & ~(size_t)3) +
                (size_t)expect_w * GLYPH_H * sizeof(Px);
  CHECK(a.top - a.static_top == want);

  /* repaint: ink pixels take the SET-RGB tint and keep the table alpha */
  bitmap_invalidate(&t, ln.cache, (Rect){0, 0, (int16_t)expect_w, GLYPH_H}, true);
  bitmap_repaint(&t, ln.cache);
  const Px *px = t.b[ln.cache].pixels;
  int ink = 0;
  int bad = 0;
  int x0 = t.b[ln.idxlist[0]].w + 1; /* 'H' is the second glyph */
  const GlyphEntry *ei = glyph_find(&kFont, 'i');
  for (int y = 0; y < GLYPH_H; y++) {
    for (int x = 0; x < ei->width; x++) {
      uint8_t al = kGlyphAlpha[ei->offset + y * ei->width + x];
      Px p = px[y * expect_w + x0 + x];
      if (al != 0) {
        ink++;
        if (!(p.r == 200 && p.g == 100 && p.b == 50 && p.a == al)) bad++;
      } else if (p.a != 0) {
        bad++;
      }
    }
  }
  CHECK(ink > 0);
  CHECK(bad == 0);
}

int main(void) {
  test_glyph_node();
  test_line();
  if (failures) {
    printf("%d check(s) failed\n", failures);
    return 1;
  }
  printf("test_glyphtext: all checks passed\n");
  return 0;
}
