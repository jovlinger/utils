/* Host tests for the Glyph kind and text lines. glyphs_test.h is generated
 * by glyphgen.py from Helvetica (see the Makefile). */
#include <stdio.h>
#include <string.h>

#include "glyph.h"
#include "glyphs_test.h"

static int failures;
static int checks;

#define CHECK(cond)                                              \
  do {                                                           \
    checks++;                                                    \
    if (!(cond)) {                                               \
      failures++;                                                \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);     \
    }                                                            \
  } while (0)

#define N 32
static Bitmap tbl[N];
static const Combiner combs[] = {
    {0, 0, {0, 0, 0, 0}},
    {7, COMB_SET, {255, 0, 0, 0}}, /* SET rgb = red, alpha untouched */
};
static BitmapTable T = {tbl, N, 0, combs, 2, 0};
static const GlyphFont font = {glyph_table, GLYPH_COUNT, glyph_alpha, GLYPH_H,
                               GLYPH_B};
static uint8_t heap[16384];

static int in_alpha_set(uint8_t a) {
  for (int f = 0; f <= 64; f++)
    if (f * 255 / 64 == a) return 1;
  return 0;
}

static void test_every_glyph_node(void) {
  for (int i = 0; i < GLYPH_COUNT; i++) {
    memset(tbl, 0, sizeof tbl);
    uint16_t cp = glyph_table[i].codepoint;
    CHECK(glyph_init(&T, 1, 2, &font, cp) == 0);
    const Bitmap *g = &tbl[1];
    CHECK(g->kind == BM_GLYPH && g->parent == 2);
    CHECK(g->pix == NULL); /* no per-glyph RGBA buffer */
    CHECK(g->h == GLYPH_H && g->w == glyph_table[i].width);
    CHECK(g->alpha == glyph_alpha + glyph_table[i].offset);
    int first = 0, last = 0;
    for (int y = 0; y < g->h; y++) {
      for (int x = 0; x < g->w; x++) {
        uint8_t a = g->alpha[y * g->w + x];
        CHECK(in_alpha_set(a));
        if (a && x == 0) first = 1;
        if (a && x == g->w - 1) last = 1;
      }
    }
    if (cp != ' ') CHECK(first && last); /* width is tight to the ink */
  }
}

static void test_missing_uses_question_mark(void) {
  memset(tbl, 0, sizeof tbl);
  CHECK(glyph_init(&T, 1, 2, &font, 0x4E2D) == 0);
  const GlyphEntry *q = glyph_find(&font, '?');
  CHECK(q != NULL);
  CHECK(tbl[1].codepoint == '?' && tbl[1].w == q->width);
  CHECK(tbl[1].alpha == glyph_alpha + q->offset);
}

static const uint8_t *cpx(int x, int y) {
  return tbl[1].pix + ((size_t)y * (size_t)tbl[1].w + (size_t)x) * 4;
}

/* idx: 1 line cache, 2 L2R, 3.. glyphs */
static void test_line_and_tint(void) {
  Arena a;
  const char *text = "Hip?";
  memset(tbl, 0, sizeof tbl);
  T.samples = 0;
  arena_init(&a, heap, sizeof heap);
  arena_seal(&a);
  size_t before = a.top;
  CHECK(text_line_build(&a, &T, &font, 1, 2, 3, 0, text, 1, 1) == 0);

  int n = (int)strlen(text);
  int sum = 0;
  for (int i = 0; i < n; i++) {
    const Bitmap *g = &tbl[3 + i];
    CHECK(g->kind == BM_GLYPH && g->pix == NULL && g->parent == 2);
    CHECK(g->h == GLYPH_H);
    sum += g->w;
  }
  CHECK(tbl[2].kind == BM_L2R && tbl[2].w == sum + (n - 1) && tbl[2].h == GLYPH_H);
  CHECK(tbl[1].kind == BM_RGBA && tbl[1].w == tbl[2].w && tbl[1].h == GLYPH_H);
  CHECK(tbl[1].child == 2 && tbl[2].parent == 1);

  /* the only heap use is one IdxList and one RGBA cache */
  size_t list_bytes = ((size_t)(n + 1) * 2 + 3) & ~(size_t)3;
  size_t cache_bytes = (size_t)tbl[1].w * (size_t)GLYPH_H * 4;
  CHECK(a.top - before == list_bytes + cache_bytes);
  CHECK((const uint8_t *)tbl[2].list >= heap &&
        (const uint8_t *)tbl[2].list < heap + sizeof heap);
  CHECK(tbl[2].list[n] == 0);

  bm_invalidate(&T, 1, (Rect){0, 0, tbl[1].w, tbl[1].h}, 1);
  bm_repaint(&T, 1);

  int inked = 0, bad = 0;
  for (int i = 0; i < n; i++) {
    int32_t ox = 0, oy = 0;
    const Bitmap *g = &tbl[3 + i];
    CHECK(bm_child_offset(&T, 2, (uint16_t)(3 + i), &ox, &oy) == 0 && oy == 0);
    for (int y = 0; y < g->h; y++) {
      for (int x = 0; x < g->w; x++) {
        uint8_t al = g->alpha[y * g->w + x];
        const uint8_t *p = cpx(ox + x, y);
        if (al) inked++;
        /* tint: rgb red, alpha equals the glyph coverage */
        if (!(p[3] == al && (al == 0 || (p[0] == 255 && p[1] == 0 && p[2] == 0))))
          bad++;
      }
    }
  }
  CHECK(inked > 0);
  CHECK(bad == 0);

  /* baseline: the H box has ink on row B-1 and none on row B */
  int32_t ox = 0, oy = 0;
  bm_child_offset(&T, 2, 3, &ox, &oy);
  int on_b1 = 0, on_b = 0;
  for (int x = 0; x < tbl[3].w; x++) {
    if (cpx(ox + x, GLYPH_B - 1)[3]) on_b1 = 1;
    if (GLYPH_B < GLYPH_H && cpx(ox + x, GLYPH_B)[3]) on_b = 1;
  }
  CHECK(on_b1 && !on_b);

  /* no combiner: ink stays white */
  tbl[2].combiner = 0;
  bm_invalidate(&T, 1, (Rect){0, 0, tbl[1].w, tbl[1].h}, 0);
  bm_repaint(&T, 1);
  bm_child_offset(&T, 2, 3, &ox, &oy);
  int white = 0;
  for (int y = 0; y < tbl[3].h; y++)
    for (int x = 0; x < tbl[3].w; x++)
      if (tbl[3].alpha[y * tbl[3].w + x] == 255) {
        const uint8_t *p = cpx(ox + x, y);
        if (p[0] == 255 && p[1] == 255 && p[2] == 255) white++;
      }
  CHECK(white > 0);
}

static void test_arena_overflow_refused(void) {
  Arena a;
  static uint8_t tiny[16];
  memset(tbl, 0, sizeof tbl);
  arena_init(&a, tiny, sizeof tiny);
  arena_seal(&a);
  CHECK(text_line_build(&a, &T, &font, 1, 2, 3, 0, "Hello", 1, 0) == -1);
}

int main(void) {
  test_every_glyph_node();
  test_missing_uses_question_mark();
  test_line_and_tint();
  test_arena_overflow_refused();
  printf("%d checks, %d failures\n", checks, failures);
  return failures ? 1 : 0;
}
