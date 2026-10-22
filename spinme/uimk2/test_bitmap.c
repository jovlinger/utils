/* Host tests for the uimk2 bitmap kinds, invalidate, and repaint. */
#include "uimk2_bitmap.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                        \
    do {                                                                   \
        checks++;                                                          \
        if (!(cond)) {                                                     \
            failures++;                                                    \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__,         \
                    __LINE__, #cond);                                      \
        }                                                                  \
    } while (0)

#define CAP 32
#define SW 40 /* root width */
#define SH 20 /* root height */
#define SENTINEL 0xEE

static uimk2_bm storage[CAP];
static uint8_t screen[SW * SH * 4];

static const uint8_t PAPER[4] = {10, 20, 30, 255};

static uimk2_rect R(int x, int y, int w, int h) {
    uimk2_rect r;
    r.x = (int16_t)x;
    r.y = (int16_t)y;
    r.w = (uint16_t)w;
    r.h = (uint16_t)h;
    return r;
}

static int rect_eq(uimk2_rect a, int x, int y, int w, int h) {
    return a.x == x && a.y == y && a.w == w && a.h == h;
}

static const uint8_t *px_at(const uint8_t *px, int w, int x, int y) {
    return &px[(y * w + x) * 4];
}

static int px_eq(const uint8_t *p, int r, int g, int b, int a) {
    return p[0] == r && p[1] == g && p[2] == b && p[3] == a;
}

/* Root Layout of SW x SH over the screen buffer, prefilled with SENTINEL. */
static uint16_t make_root(uimk2_bmtab *t, const uimk2_layout_item *items,
                          uint16_t n) {
    uint16_t root;
    uimk2_bmtab_init(t, storage, CAP);
    memset(screen, SENTINEL, sizeof screen);
    root = uimk2_bm_new(t, UIMK2_BM_LAYOUT);
    t->root = root;
    t->bm[root].w = SW;
    t->bm[root].h = SH;
    t->bm[root].u.layout.items = items;
    t->bm[root].u.layout.n = n;
    t->bm[root].u.layout.px = screen;
    memcpy(t->bm[root].u.layout.paper, PAPER, 4);
    return root;
}

static uint16_t make_glyph(uimk2_bmtab *t, uint16_t w, uint16_t h,
                           const uint8_t *alpha) {
    uint16_t g = uimk2_bm_new(t, UIMK2_BM_GLYPH);
    t->bm[g].w = w;
    t->bm[g].h = h;
    t->bm[g].u.glyph.alpha = alpha;
    return g;
}

static uint16_t make_raster(uimk2_bmtab *t, uint16_t w, uint16_t h,
                            uint8_t *px) {
    uint16_t r = uimk2_bm_new(t, UIMK2_BM_RGBA);
    t->bm[r].w = w;
    t->bm[r].h = h;
    t->bm[r].u.rgba.px = px;
    return r;
}

static void fill(uint8_t *px, int n, int r, int g, int b, int a) {
    int i;
    for (i = 0; i < n; i++) {
        px[i * 4 + 0] = (uint8_t)r;
        px[i * 4 + 1] = (uint8_t)g;
        px[i * 4 + 2] = (uint8_t)b;
        px[i * 4 + 3] = (uint8_t)a;
    }
}

/* ---- kinds and parent index ------------------------------------------- */

static void test_kinds_offsets_and_measure(void) {
    uimk2_bmtab t;
    static uint8_t a3x4[12], a2x6[12], a5x2[10];
    static uint8_t raster[6 * 6 * 4];
    static uint16_t l2r_items[4], t2b_items[4];
    static uimk2_layout_item items[3];
    uint16_t root, g1, g2, g3, l2r, t2b, ras, vp, lay;
    int32_t dx, dy;

    root = make_root(&t, items, 0);
    g1 = make_glyph(&t, 3, 4, a3x4);
    g2 = make_glyph(&t, 2, 6, a2x6);
    g3 = make_glyph(&t, 5, 2, a5x2);
    CHECK(g1 == 2 && g2 == 3 && g3 == 4); /* index 0 null, root is 1 */
    CHECK(t.bm[0].kind == UIMK2_BM_NULL);

    /* L2R: width = sum + seps, height = max, bottom-aligned */
    l2r = uimk2_bm_new(&t, UIMK2_BM_L2R);
    l2r_items[0] = g1;
    l2r_items[1] = g2;
    l2r_items[2] = 0;
    t.bm[l2r].u.pack.items = l2r_items;
    t.bm[l2r].u.pack.sep = 1;
    t.bm[g1].parent = l2r;
    t.bm[g2].parent = l2r;
    uimk2_bm_measure(&t, l2r);
    CHECK(t.bm[l2r].w == 3 + 1 + 2);
    CHECK(t.bm[l2r].h == 6);
    CHECK(uimk2_bm_child_offset(&t, l2r, g1, &dx, &dy) && dx == 0 && dy == 2);
    CHECK(uimk2_bm_child_offset(&t, l2r, g2, &dx, &dy) && dx == 4 && dy == 0);
    CHECK(!uimk2_bm_child_offset(&t, l2r, g3, &dx, &dy));

    /* T2B: height = sum + seps, width = max, centered */
    t2b = uimk2_bm_new(&t, UIMK2_BM_T2B);
    t2b_items[0] = l2r;
    t2b_items[1] = g3;
    t2b_items[2] = 0;
    t.bm[t2b].u.pack.items = t2b_items;
    t.bm[t2b].u.pack.sep = 2;
    t.bm[l2r].parent = t2b;
    t.bm[g3].parent = t2b;
    uimk2_bm_measure(&t, t2b);
    CHECK(t.bm[t2b].w == 6);
    CHECK(t.bm[t2b].h == 6 + 2 + 2);
    CHECK(uimk2_bm_child_offset(&t, t2b, l2r, &dx, &dy) && dx == 0 && dy == 0);
    CHECK(uimk2_bm_child_offset(&t, t2b, g3, &dx, &dy) && dx == 0 && dy == 8);

    /* Viewport: the child sits at minus the origin */
    ras = make_raster(&t, 6, 6, raster);
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = 3;
    t.bm[vp].h = 2;
    t.bm[vp].u.viewport.child = ras;
    t.bm[vp].u.viewport.ox = 2;
    t.bm[vp].u.viewport.oy = 1;
    t.bm[ras].parent = vp;
    CHECK(uimk2_bm_child_offset(&t, vp, ras, &dx, &dy) && dx == -2 &&
          dy == -1);

    /* Layout: LayoutItem x, y */
    lay = uimk2_bm_new(&t, UIMK2_BM_LAYOUT);
    items[0].x = 7;
    items[0].y = -3;
    items[0].idx = t2b;
    items[1].x = 1;
    items[1].y = 2;
    items[1].idx = vp;
    t.bm[lay].u.layout.items = items;
    t.bm[lay].u.layout.n = 2;
    t.bm[t2b].parent = lay;
    t.bm[vp].parent = lay;
    CHECK(uimk2_bm_child_offset(&t, lay, t2b, &dx, &dy) && dx == 7 &&
          dy == -3);
    CHECK(uimk2_bm_child_offset(&t, lay, vp, &dx, &dy) && dx == 1 && dy == 2);
    CHECK(t.bm[root].kind == UIMK2_BM_LAYOUT && t.bm[root].parent == 0);

    /* the table refuses past cap */
    while (t.count < CAP) {
        CHECK(uimk2_bm_new(&t, UIMK2_BM_RGBA) != 0);
    }
    CHECK(uimk2_bm_new(&t, UIMK2_BM_RGBA) == 0);
}

/* Each kind's samples, read back through an RGBA owner and the root. */
static void test_kinds_sample(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[2];
    static uint8_t raster[4 * 4 * 4];
    static uint8_t cache[3 * 2 * 4];
    static const uint8_t alpha[2 * 2] = {0, 64, 128, 255};
    uint16_t root, ras, vp, line, g;
    int x, y;

    root = make_root(&t, items, 0);
    /* raster pixel (x, y) = (x, y, 0, 255) */
    ras = make_raster(&t, 4, 4, raster);
    for (y = 0; y < 4; y++) {
        for (x = 0; x < 4; x++) {
            uint8_t *p = &raster[(y * 4 + x) * 4];
            p[0] = (uint8_t)x;
            p[1] = (uint8_t)y;
            p[2] = 0;
            p[3] = 255;
        }
    }
    /* Viewport 3x2 at origin (1, 2) */
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = 3;
    t.bm[vp].h = 2;
    t.bm[vp].u.viewport.child = ras;
    t.bm[vp].u.viewport.ox = 1;
    t.bm[vp].u.viewport.oy = 2;
    t.bm[ras].parent = vp;
    /* RGBA line cache with a transparent paper over the viewport */
    line = make_raster(&t, 3, 2, cache);
    t.bm[line].u.rgba.child = vp;
    t.bm[vp].parent = line;
    /* a glyph straight onto the root */
    g = make_glyph(&t, 2, 2, alpha);

    items[0].x = 0;
    items[0].y = 0;
    items[0].idx = line;
    items[1].x = 10;
    items[1].y = 10;
    items[1].idx = g;
    t.bm[root].u.layout.n = 2;
    t.bm[line].parent = root;
    t.bm[g].parent = root;

    uimk2_invalidate(&t, vp, R(0, 0, 3, 2), false);
    uimk2_invalidate(&t, g, R(0, 0, 2, 2), false);
    uimk2_repaint(&t);

    /* viewport samples child at (ox + x, oy + y) and clips to 3x2 */
    for (y = 0; y < 2; y++) {
        for (x = 0; x < 3; x++) {
            CHECK(px_eq(px_at(cache, 3, x, y), x + 1, y + 2, 0, 255));
            CHECK(px_eq(px_at(screen, SW, x, y), x + 1, y + 2, 0, 255));
        }
    }
    /* inside the root damage rect but outside every child: paper */
    CHECK(px_eq(px_at(screen, SW, 3, 0), 10, 20, 30, 255));
    /* outside the root damage rect (0, 0, 12, 12): not written */
    CHECK(px_eq(px_at(screen, SW, 12, 0), SENTINEL, SENTINEL, SENTINEL,
                SENTINEL));

    /* glyph: white RGB, alpha is coverage, over the root paper */
    CHECK(px_eq(px_at(screen, SW, 10, 10), 10, 20, 30, 255)); /* alpha 0 */
    CHECK(px_eq(px_at(screen, SW, 11, 11), 255, 255, 255, 255));
    /* alpha 64 over paper: 64 white + 191 paper, rounded */
    CHECK(px_eq(px_at(screen, SW, 11, 10), 71, 79, 86, 255));
}

/* ---- invalidate -------------------------------------------------------- */

static void test_invalidate_walks_parents(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[2];
    static uint8_t cache_a[8 * 4 * 4], cache_b[8 * 4 * 4];
    static uint8_t a3x4[12], a2x2[4];
    static uint16_t list[3];
    static uint8_t raster[10 * 10 * 4];
    uint16_t root, line_a, line_b, l2r, g1, g2, vp, ras;

    root = make_root(&t, items, 0);
    g1 = make_glyph(&t, 3, 4, a3x4);
    g2 = make_glyph(&t, 2, 2, a2x2);
    l2r = uimk2_bm_new(&t, UIMK2_BM_L2R);
    list[0] = g1;
    list[1] = g2;
    list[2] = 0;
    t.bm[l2r].u.pack.items = list;
    t.bm[l2r].u.pack.sep = 1;
    t.bm[g1].parent = l2r;
    t.bm[g2].parent = l2r;
    uimk2_bm_measure(&t, l2r); /* 6 x 4; g2 at (4, 2) */
    line_a = make_raster(&t, t.bm[l2r].w, t.bm[l2r].h, cache_a);
    t.bm[line_a].u.rgba.child = l2r;
    t.bm[l2r].parent = line_a;

    ras = make_raster(&t, 10, 10, raster);
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = 4;
    t.bm[vp].h = 4;
    t.bm[vp].u.viewport.child = ras;
    t.bm[vp].u.viewport.ox = 3;
    t.bm[vp].u.viewport.oy = 5;
    t.bm[ras].parent = vp;
    line_b = make_raster(&t, 4, 4, cache_b);
    t.bm[line_b].u.rgba.child = vp;
    t.bm[vp].parent = line_b;

    items[0].x = 5;
    items[0].y = 3;
    items[0].idx = line_a;
    items[1].x = 20;
    items[1].y = 10;
    items[1].idx = line_b;
    t.bm[root].u.layout.n = 2;
    t.bm[line_a].parent = root;
    t.bm[line_b].parent = root;

    /* one pixel of g2, walked up to the root */
    uimk2_invalidate(&t, g2, R(1, 0, 1, 1), false);
    CHECK(t.bm[g2].dirty && rect_eq(t.bm[g2].damage, 1, 0, 1, 1));
    CHECK(t.bm[l2r].dirty && rect_eq(t.bm[l2r].damage, 5, 2, 1, 1));
    CHECK(t.bm[line_a].dirty && rect_eq(t.bm[line_a].damage, 5, 2, 1, 1));
    CHECK(t.bm[root].dirty && rect_eq(t.bm[root].damage, 10, 5, 1, 1));
    CHECK(!t.bm[g2].geom_dirty && !t.bm[root].geom_dirty);
    /* nothing outside the parent chain is touched */
    CHECK(!t.bm[g1].dirty && !t.bm[line_b].dirty && !t.bm[vp].dirty);

    /* a second rect unions, and geometry ors in */
    uimk2_invalidate(&t, g1, R(0, 0, 2, 1), true);
    CHECK(rect_eq(t.bm[g1].damage, 0, 0, 2, 1));
    CHECK(rect_eq(t.bm[l2r].damage, 0, 0, 6, 3));
    CHECK(rect_eq(t.bm[root].damage, 5, 3, 6, 3));
    CHECK(t.bm[g1].geom_dirty && t.bm[l2r].geom_dirty &&
          t.bm[root].geom_dirty);
    CHECK(!t.bm[g2].geom_dirty); /* the first walk had geometry false */

    /* a viewport subtracts its origin; each level clips to its box */
    uimk2_invalidate(&t, ras, R(4, 6, 10, 10), false);
    CHECK(rect_eq(t.bm[ras].damage, 4, 6, 6, 4));
    CHECK(rect_eq(t.bm[vp].damage, 1, 1, 3, 3));
    CHECK(rect_eq(t.bm[line_b].damage, 1, 1, 3, 3));
    CHECK(rect_eq(t.bm[root].damage, 5, 3, 19, 11)); /* union with 21,11 */
}

/* ---- repaint ----------------------------------------------------------- */

static void test_repaint_paper_and_clean_sibling(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[2];
    static uint8_t cache_a[4 * 2 * 4], cache_b[4 * 2 * 4], snap_b[4 * 2 * 4];
    static uint8_t src_a[4 * 2 * 4], src_b[4 * 2 * 4];
    static uint8_t snap_screen[SW * SH * 4];
    uint16_t root, line_a, line_b, ra, rb;
    uimk2_rect blit;
    uint32_t before;
    int x, y;

    root = make_root(&t, items, 0);
    fill(src_a, 8, 200, 0, 0, 255);
    fill(src_b, 8, 0, 200, 0, 255);
    ra = make_raster(&t, 4, 2, src_a);
    rb = make_raster(&t, 4, 2, src_b);
    line_a = make_raster(&t, 4, 2, cache_a);
    line_b = make_raster(&t, 4, 2, cache_b);
    t.bm[line_a].u.rgba.child = ra;
    t.bm[line_b].u.rgba.child = rb;
    t.bm[ra].parent = line_a;
    t.bm[rb].parent = line_b;
    items[0].x = 2;
    items[0].y = 2;
    items[0].idx = line_a;
    items[1].x = 2;
    items[1].y = 10;
    items[1].idx = line_b;
    t.bm[root].u.layout.n = 2;
    t.bm[line_a].parent = root;
    t.bm[line_b].parent = root;

    /* paper fills the damage rect where no child covers; outside the rect
     * the buffer is not written */
    uimk2_invalidate(&t, root, R(20, 4, 5, 3), false);
    blit = uimk2_repaint(&t);
    CHECK(rect_eq(blit, 20, 4, 5, 3));
    for (y = 0; y < SH; y++) {
        for (x = 0; x < SW; x++) {
            const uint8_t *p = px_at(screen, SW, x, y);
            if (x >= 20 && x < 25 && y >= 4 && y < 7) {
                CHECK(px_eq(p, 10, 20, 30, 255));
            } else {
                CHECK(px_eq(p, SENTINEL, SENTINEL, SENTINEL, SENTINEL));
            }
        }
    }
    CHECK(!t.bm[root].dirty && !t.bm[root].geom_dirty);
    CHECK(rect_eq(t.bm[root].damage, 0, 0, 0, 0));

    /* paint both lines once */
    uimk2_invalidate(&t, ra, R(0, 0, 4, 2), true);
    uimk2_invalidate(&t, rb, R(0, 0, 4, 2), true);
    blit = uimk2_repaint(&t);
    CHECK(rect_eq(blit, 2, 2, 4, 10));
    CHECK(px_eq(px_at(screen, SW, 2, 2), 200, 0, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 5, 11), 0, 200, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 3, 6), 10, 20, 30, 255)); /* between */

    /* change line A only: line B's cache and its screen pixels stay */
    fill(src_a, 8, 0, 0, 200, 255);
    uimk2_invalidate(&t, ra, R(0, 0, 4, 2), false);
    CHECK(!t.bm[line_b].dirty);
    before = t.samples;
    memset(cache_b, 0x55, sizeof cache_b); /* a repaint of B would overwrite */
    memcpy(snap_b, cache_b, sizeof cache_b);
    memcpy(snap_screen, screen, sizeof screen);
    blit = uimk2_repaint(&t);
    CHECK(rect_eq(blit, 2, 2, 4, 2));
    CHECK(memcmp(cache_b, snap_b, sizeof cache_b) == 0);
    CHECK(px_eq(px_at(cache_a, 4, 0, 0), 0, 0, 200, 255));
    for (y = 0; y < SH; y++) {
        for (x = 0; x < SW; x++) {
            const uint8_t *p = px_at(screen, SW, x, y);
            if (x >= 2 && x < 6 && y >= 2 && y < 4) {
                CHECK(px_eq(p, 0, 0, 200, 255));
            } else {
                CHECK(memcmp(p, px_at(snap_screen, SW, x, y), 4) == 0);
            }
        }
    }
    /* 8 line-A cache pixels sample ra once each; 8 root pixels walk two
     * items, front (line B) misses, then line A hits opaque */
    CHECK(t.samples - before == 8 + 8 * 2);

    /* a clean frame writes nothing */
    memcpy(snap_screen, screen, sizeof screen);
    before = t.samples;
    blit = uimk2_repaint(&t);
    CHECK(rect_eq(blit, 0, 0, 0, 0));
    CHECK(t.samples == before);
    CHECK(memcmp(screen, snap_screen, sizeof screen) == 0);
}

static void test_opaque_stops_blend(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[2];
    static uint8_t back[2 * 2 * 4], front[2 * 2 * 4];
    uint16_t root, rb, rf;
    uint32_t before;

    root = make_root(&t, items, 0);
    rb = make_raster(&t, 2, 2, back);
    rf = make_raster(&t, 2, 2, front);
    fill(back, 4, 0, 0, 255, 255);
    items[0].x = 0; /* back to front: items[1] is in front */
    items[0].y = 0;
    items[0].idx = rb;
    items[1].x = 0;
    items[1].y = 0;
    items[1].idx = rf;
    t.bm[root].u.layout.n = 2;
    t.bm[rb].parent = root;
    t.bm[rf].parent = root;

    /* opaque front: one sample per pixel, the back is never read */
    fill(front, 4, 255, 0, 0, 255);
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == 4);
    CHECK(px_eq(px_at(screen, SW, 1, 1), 255, 0, 0, 255));

    /* half-alpha front: both are sampled and blended src-over */
    fill(front, 4, 255, 0, 0, 128);
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == 8);
    CHECK(px_eq(px_at(screen, SW, 0, 0), 128, 0, 127, 255));

    /* (0,0,0,0) is a real color, not a miss: it covers, adds nothing, and
     * the back shows through */
    fill(front, 4, 0, 0, 0, 0);
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == 8);
    CHECK(px_eq(px_at(screen, SW, 0, 0), 0, 0, 255, 255));
}

int main(void) {
    test_kinds_offsets_and_measure();
    test_kinds_sample();
    test_invalidate_walks_parents();
    test_repaint_paper_and_clean_sibling();
    test_opaque_stops_blend();
    printf("test_bitmap: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
