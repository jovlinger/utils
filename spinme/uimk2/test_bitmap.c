/* Host test for the bitmap kinds and repaint. Build and run: make -C spinme test */
#include <stdio.h>
#include <string.h>

#include "bitmap.h"

static int failures = 0;
#define CHECK(c)                                                  \
  do {                                                            \
    if (!(c)) {                                                   \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);         \
      failures++;                                                 \
    }                                                             \
  } while (0)

static bool px_eq(Px p, uint8_t r, uint8_t g, uint8_t b, uint8_t a) {
  return p.r == r && p.g == g && p.b == b && p.a == a;
}

static bool rect_eq(Rect r, int x, int y, int w, int h) {
  return r.x == x && r.y == y && r.w == w && r.h == h;
}

enum { CAP = 32, RW = 40, RH = 30 };

typedef struct {
  BitmapTable t;
  Bitmap store[CAP];
  LayoutItem items[CAP][4];
  int next_items;
} Fix;

static uint16_t mk(Fix *f, BitmapKind k, uint16_t w, uint16_t h) {
  uint16_t i = bitmap_new(&f->t, k, w, h);
  if (k == BK_LAYOUT || k == BK_L2R || k == BK_T2B) {
    f->t.b[i].items = f->items[f->next_items++];
    f->t.b[i].items_cap = 4;
  }
  return i;
}

/* Glyph 3x4 ink: alpha 255 on column 0, 128 on column 1, 0 on column 2. */
static const uint8_t kGlyphA[12] = {255, 128, 0, 255, 128, 0,
                                    255, 128, 0, 255, 128, 0};
static const uint8_t kGlyphB[8] = {64, 64, 64, 64, 64, 64, 64, 64}; /* 2x4 */

static void test_parent_and_invalidate(void) {
  Fix f;
  Px root_px[RW * RH];
  bitmap_table_init(&f.t, f.store, CAP);
  f.next_items = 0;

  uint16_t root = mk(&f, BK_LAYOUT, RW, RH);
  uint16_t line = mk(&f, BK_RGBA, 10, 4);
  Px line_px[10 * 4];
  uint16_t l2r = mk(&f, BK_L2R, 0, 0);
  uint16_t g1 = mk(&f, BK_GLYPH, 3, 4);
  uint16_t g2 = mk(&f, BK_GLYPH, 2, 4);
  f.t.b[root].pixels = root_px;
  f.t.b[line].pixels = line_px;
  f.t.b[g1].alpha = kGlyphA;
  f.t.b[g2].alpha = kGlyphB;
  f.t.b[l2r].hsep = 1;

  CHECK(root == 1);
  CHECK(f.t.b[0].kind == BK_NONE);
  CHECK(bitmap_add(&f.t, l2r, g1, 0, 0));
  CHECK(bitmap_add(&f.t, l2r, g2, 0, 0));
  CHECK(bitmap_set_child(&f.t, line, l2r));
  CHECK(bitmap_add(&f.t, root, line, 20, 10));
  bitmap_pack(&f.t, l2r);

  /* one parent index per node, glyph's parent is the line that uses it */
  CHECK(f.t.b[g1].parent == l2r);
  CHECK(f.t.b[g2].parent == l2r);
  CHECK(f.t.b[l2r].parent == line);
  CHECK(f.t.b[line].parent == root);
  CHECK(f.t.b[root].parent == 0);
  CHECK(!bitmap_add(&f.t, root, g1, 0, 0));      /* second parent refused */
  CHECK(!bitmap_set_child(&f.t, line, g1));

  /* L2R: width is sum of widths plus seps, height is the max */
  CHECK(f.t.b[l2r].w == 3 + 1 + 2);
  CHECK(f.t.b[l2r].h == 4);
  CHECK(f.t.b[l2r].items[0].x == 0);
  CHECK(f.t.b[l2r].items[1].x == 4);

  /* invalidate glyph g2 (local 0,1 size 2x1): walks parents, adds item offsets */
  Rect r = {0, 1, 2, 1};
  bitmap_invalidate(&f.t, g2, r, false);
  CHECK(f.t.b[g2].dirty && f.t.b[l2r].dirty && f.t.b[line].dirty && f.t.b[root].dirty);
  CHECK(!f.t.b[g1].dirty);                       /* sibling untouched */
  CHECK(rect_eq(f.t.b[g2].damage, 0, 1, 2, 1));
  CHECK(rect_eq(f.t.b[l2r].damage, 4, 1, 2, 1));
  CHECK(rect_eq(f.t.b[line].damage, 4, 1, 2, 1));
  CHECK(rect_eq(f.t.b[root].damage, 24, 11, 2, 1));
  CHECK(!f.t.b[root].geom_dirty);

  /* second invalidate unions; geometry flag ors up the chain */
  Rect r2 = {0, 0, 1, 1};
  bitmap_invalidate(&f.t, g1, r2, true);
  CHECK(rect_eq(f.t.b[l2r].damage, 0, 0, 6, 2));
  CHECK(rect_eq(f.t.b[root].damage, 20, 10, 6, 2));
  CHECK(f.t.b[g1].geom_dirty && f.t.b[root].geom_dirty);
  CHECK(!f.t.b[g2].geom_dirty);
}

static void test_viewport_and_layout_kinds(void) {
  Fix f;
  bitmap_table_init(&f.t, f.store, CAP);
  f.next_items = 0;

  /* Viewport: samples child at (ox+x, oy+y); invalidate subtracts the origin */
  uint16_t vp = mk(&f, BK_VIEWPORT, 4, 4);
  uint16_t big = mk(&f, BK_RGBA, 20, 20);
  f.t.b[vp].ox = 10;
  f.t.b[vp].oy = 6;
  CHECK(bitmap_set_child(&f.t, vp, big));
  Rect in = {12, 8, 2, 2};
  bitmap_invalidate(&f.t, big, in, false);
  CHECK(rect_eq(f.t.b[big].damage, 12, 8, 2, 2));
  CHECK(rect_eq(f.t.b[vp].damage, 2, 2, 2, 2));
  Rect out = {0, 0, 5, 5}; /* wholly outside the window: clipped away */
  bitmap_invalidate(&f.t, big, out, false);
  CHECK(rect_eq(f.t.b[vp].damage, 2, 2, 2, 2));

  /* T2B: height is sum plus vsep, width is max, cross axis centered */
  uint16_t t2b = mk(&f, BK_T2B, 0, 0);
  uint16_t a = mk(&f, BK_RGBA, 10, 3);
  uint16_t b = mk(&f, BK_RGBA, 4, 5);
  f.t.b[t2b].vsep = 2;
  CHECK(bitmap_add(&f.t, t2b, a, 0, 0));
  CHECK(bitmap_add(&f.t, t2b, b, 0, 0));
  bitmap_pack(&f.t, t2b);
  CHECK(f.t.b[t2b].w == 10);
  CHECK(f.t.b[t2b].h == 3 + 2 + 5);
  CHECK(f.t.b[t2b].items[0].x == 0 && f.t.b[t2b].items[0].y == 0);
  CHECK(f.t.b[t2b].items[1].x == 3 && f.t.b[t2b].items[1].y == 5);

  /* L2R: cross axis is bottom, so a short child shares the baseline */
  uint16_t l2r = mk(&f, BK_L2R, 0, 0);
  uint16_t s = mk(&f, BK_RGBA, 2, 3);
  uint16_t tall = mk(&f, BK_RGBA, 5, 8);
  f.t.b[l2r].hsep = 3;
  CHECK(bitmap_add(&f.t, l2r, s, 0, 0));
  CHECK(bitmap_add(&f.t, l2r, tall, 0, 0));
  bitmap_pack(&f.t, l2r);
  CHECK(f.t.b[l2r].w == 2 + 3 + 5);
  CHECK(f.t.b[l2r].h == 8);
  CHECK(f.t.b[l2r].items[0].y == 5);
  CHECK(f.t.b[l2r].items[1].y == 0);
}

static void test_repaint(void) {
  Fix f;
  Px root_px[RW * RH];
  Px la_px[8 * 4], lb_px[8 * 4];
  bitmap_table_init(&f.t, f.store, CAP);
  f.next_items = 0;

  uint16_t root = mk(&f, BK_LAYOUT, RW, RH);
  uint16_t la = mk(&f, BK_RGBA, 8, 4); /* line A at (2,2) */
  uint16_t lb = mk(&f, BK_RGBA, 8, 4); /* sibling line B at (2,10) */
  uint16_t ga = mk(&f, BK_GLYPH, 3, 4);
  f.t.b[root].pixels = root_px;
  f.t.b[la].pixels = la_px;
  f.t.b[lb].pixels = lb_px;
  f.t.b[ga].alpha = kGlyphA;
  f.t.b[root].paper = (Px){10, 20, 30, 255};
  f.t.b[la].paper = (Px){0, 0, 0, 0};
  CHECK(bitmap_add(&f.t, root, la, 2, 2));
  CHECK(bitmap_add(&f.t, root, lb, 2, 10));
  CHECK(bitmap_set_child(&f.t, la, ga));

  /* sentinel everywhere so any stray write shows */
  Px sentinel = {1, 2, 3, 4};
  for (int i = 0; i < RW * RH; i++) {
    root_px[i] = sentinel;
  }
  for (int i = 0; i < 32; i++) {
    la_px[i] = sentinel;
    lb_px[i] = (Px){200, 100, 50, 255}; /* opaque marker for the sibling */
  }

  /* clean tree: repaint writes nothing */
  bitmap_repaint(&f.t, root);
  CHECK(px_eq(root_px[0], 1, 2, 3, 4));
  CHECK(f.t.b[root].repaints == 0);

  /* dirty line A in a 6x2 box at (1,1): paper where no child covers */
  Rect r = {1, 1, 6, 2};
  bitmap_invalidate(&f.t, la, r, false);
  CHECK(rect_eq(f.t.b[root].damage, 3, 3, 6, 2));
  bitmap_repaint(&f.t, root);

  /* line A cache: glyph covers x 0..2, y 0..3. Inside damage: x 1..6, y 1..2 */
  CHECK(px_eq(la_px[1 * 8 + 1], 255, 255, 255, 128)); /* glyph col 1 over paper(0,0,0,0) */
  CHECK(px_eq(la_px[1 * 8 + 2], 0, 0, 0, 0));          /* glyph col 2 alpha 0, paper */
  CHECK(px_eq(la_px[1 * 8 + 4], 0, 0, 0, 0));          /* uncovered: paper */
  CHECK(px_eq(la_px[0 * 8 + 0], 1, 2, 3, 4));          /* outside damage: untouched */
  CHECK(px_eq(la_px[1 * 8 + 0], 1, 2, 3, 4));          /* x 0 is outside damage */
  CHECK(px_eq(la_px[3 * 8 + 3], 1, 2, 3, 4));

  /* root: line A (2,2) is front of paper. Pixel (3,3) is line px (1,1) */
  CHECK(px_eq(root_px[3 * RW + 4], 10, 20, 30, 255)); /* line px (2,1): alpha 0 */
  /* line A has alpha 128 white at line (1,1); root paper is (10,20,30,255) */
  Px p = root_px[3 * RW + 3];
  CHECK(p.a == 255);
  CHECK(p.r >= 128 && p.r <= 136); /* between paper 10 and white 255 */
  /* an uncovered root pixel inside damage but outside line A shows paper */
  CHECK(px_eq(root_px[2 * RW + 3], 1, 2, 3, 4));       /* y=2 is outside damage */

  /* clean sibling line B: untouched, not repainted, and its root area unchanged */
  CHECK(f.t.b[lb].repaints == 0);
  CHECK(!f.t.b[lb].dirty);
  CHECK(px_eq(lb_px[0], 200, 100, 50, 255));
  CHECK(px_eq(root_px[10 * RW + 2], 1, 2, 3, 4));
  CHECK(px_eq(root_px[RH * RW - 1], 1, 2, 3, 4));

  /* flags cleared after the write */
  CHECK(!f.t.b[root].dirty && !f.t.b[la].dirty && !f.t.b[ga].dirty);
  CHECK(!f.t.b[root].geom_dirty);
  CHECK(rect_eq(f.t.b[root].damage, 0, 0, 0, 0));
  CHECK(f.t.b[root].repaints == 1 && f.t.b[la].repaints == 1);

  /* a damaged root pixel no child covers becomes the root paper color */
  Rect hole = {30, 20, 2, 2};
  bitmap_invalidate(&f.t, root, hole, false);
  bitmap_repaint(&f.t, root);
  CHECK(px_eq(root_px[20 * RW + 30], 10, 20, 30, 255));
  CHECK(px_eq(root_px[21 * RW + 31], 10, 20, 30, 255));
  CHECK(px_eq(root_px[20 * RW + 32], 1, 2, 3, 4));
  CHECK(f.t.b[la].repaints == 1); /* line A was not dirty, not repainted */

  /* a clean frame is a no-op */
  unsigned before = f.t.b[root].repaints;
  bitmap_repaint(&f.t, root);
  CHECK(f.t.b[root].repaints == before);
}

static void test_opaque_stops_blend(void) {
  Fix f;
  Px root_px[RW * RH];
  Px front_px[4 * 4], back_px[4 * 4];
  bitmap_table_init(&f.t, f.store, CAP);
  f.next_items = 0;

  uint16_t root = mk(&f, BK_LAYOUT, RW, RH);
  uint16_t back = mk(&f, BK_RGBA, 4, 4);
  uint16_t front = mk(&f, BK_RGBA, 4, 4);
  f.t.b[root].pixels = root_px;
  f.t.b[back].pixels = back_px;
  f.t.b[front].pixels = front_px;
  f.t.b[root].paper = (Px){0, 0, 0, 255};
  for (int i = 0; i < 16; i++) {
    back_px[i] = (Px){0, 255, 0, 255};
    front_px[i] = (Px){255, 0, 0, 255};
  }
  /* later items are in front */
  CHECK(bitmap_add(&f.t, root, back, 0, 0));
  CHECK(bitmap_add(&f.t, root, front, 0, 0));

  Rect r = {0, 0, 4, 4};
  bitmap_invalidate(&f.t, root, r, false);
  f.t.samples = 0;
  bitmap_repaint(&f.t, root);
  CHECK(px_eq(root_px[0], 255, 0, 0, 255));
  CHECK(f.t.samples == 16); /* one sample per pixel: the back child is never read */

  /* translucent front blends with the back child, then the paper never shows */
  for (int i = 0; i < 16; i++) {
    front_px[i] = (Px){255, 0, 0, 128};
  }
  bitmap_invalidate(&f.t, root, r, false);
  f.t.samples = 0;
  bitmap_repaint(&f.t, root);
  CHECK(f.t.samples == 32);
  CHECK(root_px[0].a == 255);
  CHECK(root_px[0].r > 120 && root_px[0].r < 135);
  CHECK(root_px[0].g > 120 && root_px[0].g < 135);
  CHECK(root_px[0].b == 0);

  /* (0,0,0,0) is a real color: it covers but adds nothing */
  for (int i = 0; i < 16; i++) {
    front_px[i] = (Px){0, 0, 0, 0};
  }
  bitmap_invalidate(&f.t, root, r, false);
  bitmap_repaint(&f.t, root);
  CHECK(px_eq(root_px[0], 0, 255, 0, 255));
}

static void test_glyph_has_no_pixel_buffer(void) {
  Fix f;
  bitmap_table_init(&f.t, f.store, CAP);
  uint16_t g = bitmap_new(&f.t, BK_GLYPH, 3, 4);
  f.t.b[g].alpha = kGlyphA;
  CHECK(f.t.b[g].pixels == NULL);
  CHECK(f.t.b[g].alpha == kGlyphA);
  CHECK(bitmap_new(&f.t, BK_RGBA, 1, 1) != 0);
  /* table full returns 0 */
  while (bitmap_new(&f.t, BK_RGBA, 1, 1) != 0) {
  }
  CHECK(bitmap_new(&f.t, BK_RGBA, 1, 1) == 0);
}

int main(void) {
  test_parent_and_invalidate();
  test_viewport_and_layout_kinds();
  test_repaint();
  test_opaque_stops_blend();
  test_glyph_has_no_pixel_buffer();
  if (failures) {
    printf("%d check(s) failed\n", failures);
    return 1;
  }
  printf("test_bitmap: all checks passed\n");
  return 0;
}
