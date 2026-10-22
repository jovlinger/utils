/* Host tests for the uimk2 bitmap kinds and repaint. */
#include <stdio.h>
#include <string.h>

#include "bitmap.h"

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

#define N 16
static Bitmap tbl[N];
static BitmapTable T = {tbl, N, 0, NULL, 0};

static void reset(void) {
  memset(tbl, 0, sizeof tbl);
  T.samples = 0;
}

static uint8_t *px(Bitmap *b, int x, int y) {
  return b->pix + ((size_t)y * (size_t)b->w + (size_t)x) * 4;
}

static int is(const uint8_t *p, int r, int g, int bl, int a) {
  return p[0] == r && p[1] == g && p[2] == bl && p[3] == a;
}

static void init_node(int idx, BitmapKind k, int parent, int w, int h) {
  tbl[idx].kind = (uint8_t)k;
  tbl[idx].parent = (uint16_t)parent;
  tbl[idx].w = w;
  tbl[idx].h = h;
}

/* Two text lines under a root. Each line is an RGBA cache whose child is an
 * L2R of two glyphs. */
static uint8_t root_pix[20 * 10 * 4], a_pix[6 * 3 * 4], b_pix[6 * 3 * 4];
static uint8_t gA_alpha[2 * 3], gB_alpha[2 * 3], gC_alpha[2 * 2], gD_alpha[2 * 3];
static const uint16_t listA[] = {4, 5, 0};
static const uint16_t listB[] = {8, 9, 0};
static LayoutItem rootItems[] = {{2, 1, 2}, {2, 6, 3}};

/* idx: 1 root, 2 lineA, 3 lineB, 4/5 glyphs of A (via L2R 6), 8/9 of B (L2R 7) */
static void build_scene(void) {
  reset();
  memset(root_pix, 0xEE, sizeof root_pix);
  memset(gA_alpha, 255, sizeof gA_alpha);
  memset(gB_alpha, 255, sizeof gB_alpha);
  memset(gC_alpha, 255, sizeof gC_alpha);
  memset(gD_alpha, 255, sizeof gD_alpha);
  init_node(1, BM_LAYOUT, 0, 20, 10);
  tbl[1].pix = root_pix;
  tbl[1].items = rootItems;
  tbl[1].nitems = 2;
  tbl[1].paper[0] = 10; tbl[1].paper[1] = 20; tbl[1].paper[2] = 30;
  tbl[1].paper[3] = 255;

  init_node(2, BM_RGBA, 1, 6, 3);
  tbl[2].pix = a_pix;
  tbl[2].child = 6;
  tbl[2].paper[3] = 255; /* black paper */
  init_node(3, BM_RGBA, 1, 6, 3);
  tbl[3].pix = b_pix;
  tbl[3].child = 7;
  tbl[3].paper[3] = 255;

  init_node(6, BM_L2R, 2, 0, 0);
  tbl[6].list = listA;
  tbl[6].sep = 1;
  init_node(7, BM_L2R, 3, 0, 0);
  tbl[7].list = listB;
  tbl[7].sep = 1;

  /* glyph 4: 2x3, glyph 5: 2x2 (shorter: bottom-aligned on the baseline) */
  init_node(4, BM_GLYPH, 6, 2, 3);
  tbl[4].alpha = gA_alpha;
  init_node(5, BM_GLYPH, 6, 2, 2);
  tbl[5].alpha = gC_alpha;
  init_node(8, BM_GLYPH, 7, 2, 3);
  tbl[8].alpha = gB_alpha;
  init_node(9, BM_GLYPH, 7, 2, 3);
  tbl[9].alpha = gD_alpha;
  bm_measure(&T, 6);
  bm_measure(&T, 7);
}

static void test_measure_and_offsets(void) {
  build_scene();
  CHECK(tbl[6].w == 5 && tbl[6].h == 3); /* 2 + sep 1 + 2, max h 3 */
  int32_t ox, oy;
  CHECK(bm_child_offset(&T, 6, 4, &ox, &oy) == 0 && ox == 0 && oy == 0);
  CHECK(bm_child_offset(&T, 6, 5, &ox, &oy) == 0 && ox == 3 && oy == 1);
  CHECK(bm_child_offset(&T, 6, 8, &ox, &oy) == -1);

  /* T2B centers on the cross axis */
  uint16_t tl[] = {4, 5, 0};
  init_node(10, BM_T2B, 0, 0, 0);
  tbl[10].list = tl;
  tbl[10].sep = 2;
  bm_measure(&T, 10);
  CHECK(tbl[10].w == 2 && tbl[10].h == 3 + 2 + 2);
  init_node(11, BM_GLYPH, 10, 4, 1);
  uint16_t tl2[] = {4, 11, 0};
  tbl[10].list = tl2;
  bm_measure(&T, 10);
  CHECK(tbl[10].w == 4);
  CHECK(bm_child_offset(&T, 10, 4, &ox, &oy) == 0 && ox == 1 && oy == 0);
  CHECK(bm_child_offset(&T, 10, 11, &ox, &oy) == 0 && ox == 0 && oy == 5);

  /* Viewport subtracts its origin; Layout adds its item offset */
  init_node(12, BM_VIEWPORT, 0, 3, 3);
  tbl[12].child = 4;
  tbl[12].ox = 1;
  tbl[12].oy = 2;
  CHECK(bm_child_offset(&T, 12, 4, &ox, &oy) == 0 && ox == -1 && oy == -2);
  CHECK(bm_child_offset(&T, 1, 3, &ox, &oy) == 0 && ox == 2 && oy == 6);
}

static void test_one_parent_and_invalidate(void) {
  build_scene();
  /* invalidate walks parent indexes only: glyph 5 -> L2R 6 -> line 2 -> root 1 */
  Rect r = {0, 0, 2, 2};
  bm_invalidate(&T, 5, r, 1);
  CHECK(tbl[5].dirty && tbl[6].dirty && tbl[2].dirty && tbl[1].dirty);
  CHECK(!tbl[4].dirty && !tbl[3].dirty && !tbl[7].dirty);
  CHECK(tbl[1].geom_dirty && tbl[5].geom_dirty && !tbl[3].geom_dirty);
  /* glyph 5 sits at (3,1) in L2R 6; line 2 at (2,1) in the root */
  CHECK(tbl[5].damage.x == 0 && tbl[5].damage.y == 0);
  CHECK(tbl[6].damage.x == 3 && tbl[6].damage.y == 1);
  CHECK(tbl[2].damage.x == 3 && tbl[2].damage.y == 1);
  CHECK(tbl[1].damage.x == 5 && tbl[1].damage.y == 2);
  CHECK(tbl[1].damage.w == 2 && tbl[1].damage.h == 2);

  /* a second invalidate unions into the existing damage */
  Rect r2 = {0, 0, 1, 1};
  bm_invalidate(&T, 4, r2, 0);
  CHECK(tbl[1].damage.x == 2 && tbl[1].damage.y == 1);
  CHECK(tbl[1].damage.w == 5 && tbl[1].damage.h == 3);
}

static void test_repaint_paper_and_clean_sibling(void) {
  build_scene();
  /* whole first paint */
  Rect all = {0, 0, 20, 10};
  bm_invalidate(&T, 1, all, 1);
  bm_invalidate(&T, 2, (Rect){0, 0, 6, 3}, 1);
  bm_invalidate(&T, 3, (Rect){0, 0, 6, 3}, 1);
  bm_repaint(&T, 1);
  CHECK(!tbl[1].dirty && !tbl[1].geom_dirty && rect_empty(tbl[1].damage));
  CHECK(!tbl[2].dirty && !tbl[3].dirty);
  /* uncovered root pixel is paper */
  CHECK(is(px(&tbl[1], 0, 0), 10, 20, 30, 255));
  CHECK(is(px(&tbl[1], 19, 9), 10, 20, 30, 255));
  /* glyph ink in line A: opaque white at (0,0) of glyph 4 -> root (2,1) */
  CHECK(is(px(&tbl[1], 2, 1), 255, 255, 255, 255));
  /* in line A, glyph 5 is 2 tall bottom aligned: its top row is a miss in
   * the line cache, so the line's black paper is there (line (3,0) -> root
   * (5,1)) */
  CHECK(is(px(&tbl[2], 3, 0), 0, 0, 0, 255));
  CHECK(is(px(&tbl[1], 5, 1), 0, 0, 0, 255));
  CHECK(is(px(&tbl[2], 3, 1), 255, 255, 255, 255));

  /* plant sentinels: one in the sibling line B's area, one outside */
  uint8_t before[20 * 10 * 4];
  px(&tbl[1], 2, 6)[0] = 77; /* sibling line B pixel, root (2,6) */
  px(&tbl[1], 15, 8)[1] = 99; /* outside any damage */
  memcpy(before, root_pix, sizeof before);

  /* change glyph 4 in line A to transparent and invalidate it */
  memset(gA_alpha, 0, sizeof gA_alpha);
  bm_invalidate(&T, 4, (Rect){0, 0, 2, 3}, 0);
  CHECK(!tbl[3].dirty);
  bm_repaint(&T, 1);
  /* damaged pixel rewritten: root (2,1) is now the line's paper (black) */
  CHECK(is(px(&tbl[1], 2, 1), 0, 0, 0, 255));
  /* clean sibling line and everything else byte-identical */
  int same = 1;
  for (int y = 0; y < 10; y++) {
    for (int x = 0; x < 20; x++) {
      int in_damage = x >= 2 && x < 4 && y >= 1 && y < 4;
      if (!in_damage && memcmp(px(&tbl[1], x, y), before + ((size_t)y * 20 + (size_t)x) * 4, 4)) same = 0;
    }
  }
  CHECK(same);
  CHECK(px(&tbl[1], 2, 6)[0] == 77 && px(&tbl[1], 15, 8)[1] == 99);

  /* a clean tree repaints nothing */
  T.samples = 0;
  bm_repaint(&T, 1);
  CHECK(T.samples == 0);
}

static void test_miss_writes_paper_in_damage_rect(void) {
  build_scene();
  /* damage a region with no child: becomes paper, rest stays sentinel */
  bm_invalidate(&T, 1, (Rect){10, 2, 4, 3}, 0);
  bm_repaint(&T, 1);
  int ok = 1, outside = 1;
  for (int y = 0; y < 10; y++) {
    for (int x = 0; x < 20; x++) {
      int in = x >= 10 && x < 14 && y >= 2 && y < 5;
      const uint8_t *p = px(&tbl[1], x, y);
      if (in && !is(p, 10, 20, 30, 255)) ok = 0;
      if (!in && !is(p, 0xEE, 0xEE, 0xEE, 0xEE)) outside = 0;
    }
  }
  CHECK(ok);
  CHECK(outside);
}

static void test_opaque_stops_blend(void) {
  reset();
  static uint8_t root[4 * 4 * 4], low[4 * 4 * 4], high[4 * 4 * 4];
  static const LayoutItem items[] = {{0, 0, 2}, {0, 0, 3}}; /* 3 in front */
  for (int i = 0; i < 16; i++) {
    memcpy(low + i * 4, (uint8_t[]){1, 2, 3, 255}, 4);
    memcpy(high + i * 4, (uint8_t[]){200, 100, 50, 255}, 4);
  }
  init_node(1, BM_LAYOUT, 0, 4, 4);
  tbl[1].pix = root;
  tbl[1].items = items;
  tbl[1].nitems = 2;
  init_node(2, BM_RGBA, 1, 4, 4);
  tbl[2].pix = low;
  init_node(3, BM_RGBA, 1, 4, 4);
  tbl[3].pix = high;
  bm_invalidate(&T, 1, (Rect){0, 0, 4, 4}, 1);
  bm_repaint(&T, 1);
  CHECK(is(px(&tbl[1], 1, 1), 200, 100, 50, 255));
  CHECK(T.samples == 16); /* one leaf read per pixel: the lower item is skipped */

  /* a translucent front item does sample the lower one and blends */
  reset();
  for (int i = 0; i < 16; i++)
    memcpy(high + i * 4, (uint8_t[]){255, 255, 255, 128}, 4);
  init_node(1, BM_LAYOUT, 0, 4, 4);
  tbl[1].pix = root;
  tbl[1].items = items;
  tbl[1].nitems = 2;
  init_node(2, BM_RGBA, 1, 4, 4);
  tbl[2].pix = low;
  init_node(3, BM_RGBA, 1, 4, 4);
  tbl[3].pix = high;
  bm_invalidate(&T, 1, (Rect){0, 0, 4, 4}, 1);
  bm_repaint(&T, 1);
  CHECK(T.samples == 32);
  const uint8_t *p = px(&tbl[1], 0, 0);
  CHECK(p[3] == 255 && p[0] > 100 && p[0] < 200);
}

static void test_transparent_rgba_is_a_real_color(void) {
  reset();
  static uint8_t root[2 * 2 * 4], src[2 * 2 * 4];
  static const LayoutItem items[] = {{0, 0, 2}};
  memset(src, 0, sizeof src); /* (0,0,0,0) */
  init_node(1, BM_LAYOUT, 0, 2, 2);
  tbl[1].pix = root;
  tbl[1].items = items;
  tbl[1].nitems = 1;
  tbl[1].paper[0] = 9; tbl[1].paper[3] = 255;
  init_node(2, BM_RGBA, 1, 2, 2);
  tbl[2].pix = src;
  bm_invalidate(&T, 1, (Rect){0, 0, 2, 2}, 1);
  bm_repaint(&T, 1);
  CHECK(is(px(&tbl[1], 0, 0), 9, 0, 0, 255)); /* shows paper through */
  CHECK(T.samples == 4);
}

static void test_viewport_clips(void) {
  reset();
  static uint8_t root[6 * 6 * 4], big[8 * 8 * 4];
  static const LayoutItem items[] = {{1, 1, 2}};
  for (int y = 0; y < 8; y++)
    for (int x = 0; x < 8; x++)
      memcpy(big + (y * 8 + x) * 4, (uint8_t[]){(uint8_t)(x * 10), (uint8_t)(y * 10), 0, 255}, 4);
  init_node(1, BM_LAYOUT, 0, 6, 6);
  tbl[1].pix = root;
  tbl[1].items = items;
  tbl[1].nitems = 1;
  tbl[1].paper[3] = 255;
  init_node(2, BM_VIEWPORT, 1, 3, 3);
  tbl[2].child = 3;
  tbl[2].ox = 4;
  tbl[2].oy = 5;
  init_node(3, BM_RGBA, 2, 8, 8);
  tbl[3].pix = big;
  bm_invalidate(&T, 3, (Rect){4, 5, 3, 3}, 0);
  /* child rect (4,5) maps to viewport (0,0), then root (1,1) */
  CHECK(tbl[1].damage.x == 1 && tbl[1].damage.y == 1);
  bm_repaint(&T, 1);
  CHECK(is(px(&tbl[1], 1, 1), 40, 50, 0, 255));
  CHECK(is(px(&tbl[1], 3, 3), 60, 70, 0, 255));
}

static void test_glyph_alpha_blend(void) {
  build_scene();
  gA_alpha[0] = 128; /* top-left of glyph 4 */
  bm_invalidate(&T, 1, (Rect){0, 0, 20, 10}, 1);
  bm_invalidate(&T, 2, (Rect){0, 0, 6, 3}, 1);
  bm_invalidate(&T, 3, (Rect){0, 0, 6, 3}, 1);
  bm_repaint(&T, 1);
  /* white at alpha 128 over the line's black paper: ~128 gray */
  const uint8_t *p = px(&tbl[2], 0, 0);
  CHECK(p[0] >= 127 && p[0] <= 129 && p[3] == 255);
}

int main(void) {
  test_measure_and_offsets();
  test_one_parent_and_invalidate();
  test_repaint_paper_and_clean_sibling();
  test_miss_writes_paper_in_damage_rect();
  test_opaque_stops_blend();
  test_transparent_rgba_is_a_real_color();
  test_viewport_clips();
  test_glyph_alpha_blend();
  printf("%d checks, %d failures\n", checks, failures);
  return failures ? 1 : 0;
}
