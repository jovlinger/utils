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

/* ---- root per-row overlap lists ---------------------------------------- */

static uint32_t row_start[SH + 1];
static uint16_t row_item[SH * 8];

static void give_rows(uimk2_bmtab *t, uint16_t root, uint32_t cap) {
    t->bm[root].u.layout.row_start = row_start;
    t->bm[root].u.layout.row_item = row_item;
    t->bm[root].u.layout.row_cap = cap;
    t->bm[root].u.layout.rows_ok = false;
}

static int row_is(int y, const uint16_t *want, int n) {
    int k;
    if ((int)(row_start[y + 1] - row_start[y]) != n) {
        return 0;
    }
    for (k = 0; k < n; k++) {
        if (row_item[row_start[y] + (uint32_t)k] != want[k]) {
            return 0;
        }
    }
    return 1;
}

static void test_root_rows(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[3];
    static uint8_t ra[4 * 2 * 4], rb[4 * 2 * 4], rc[3 * 6 * 4];
    uint16_t root, a, b, c;
    static const uint16_t front_c[1] = {2}, c_then_a[2] = {2, 0},
                          only_a[1] = {0}, only_b[1] = {1};
    uint32_t before;
    int y;

    root = make_root(&t, items, 0);
    give_rows(&t, root, SH * 8);
    a = make_raster(&t, 4, 2, ra);
    b = make_raster(&t, 4, 2, rb);
    c = make_raster(&t, 3, 6, rc);
    fill(ra, 8, 200, 0, 0, 255);
    fill(rb, 8, 0, 200, 0, 255);
    fill(rc, 18, 0, 0, 200, 255);
    items[0].x = 2; /* a: rows 2..3 */
    items[0].y = 2;
    items[0].idx = a;
    items[1].x = 2; /* b: rows 10..11 */
    items[1].y = 10;
    items[1].idx = b;
    items[2].x = 30; /* c, in front: rows 0..2, clipped above the root */
    items[2].y = -3;
    items[2].idx = c;
    t.bm[root].u.layout.n = 3;
    t.bm[a].parent = root;
    t.bm[b].parent = root;
    t.bm[c].parent = root;

    /* first repaint builds the lists even without geometry */
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), false);
    uimk2_repaint(&t);
    CHECK(t.row_rebuilds == 1 && t.bm[root].u.layout.rows_ok);
    CHECK(row_is(0, front_c, 1) && row_is(1, front_c, 1));
    CHECK(row_is(2, c_then_a, 2)); /* front to back */
    CHECK(row_is(3, only_a, 1));
    CHECK(row_is(4, NULL, 0) && row_is(9, NULL, 0));
    CHECK(row_is(10, only_b, 1) && row_is(11, only_b, 1));
    CHECK(row_is(12, NULL, 0) && row_is(SH - 1, NULL, 0));
    CHECK(px_eq(px_at(screen, SW, 2, 2), 200, 0, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 5, 11), 0, 200, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 31, 2), 0, 0, 200, 255));
    CHECK(px_eq(px_at(screen, SW, 31, 3), 10, 20, 30, 255));

    /* a non-geometry change does not rebuild, and row 3 walks only a */
    fill(ra, 8, 0, 0, 0, 255);
    uimk2_invalidate(&t, a, R(0, 1, 4, 1), false);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.row_rebuilds == 1);
    CHECK(t.samples - before == 4);
    CHECK(px_eq(px_at(screen, SW, 2, 3), 0, 0, 0, 255));

    /* move b; a geometry invalidate of old and new boxes rebuilds */
    items[1].y = 3;
    uimk2_invalidate(&t, root, R(2, 3, 4, 9), true);
    uimk2_repaint(&t);
    CHECK(t.row_rebuilds == 2);
    for (y = 4; y < SH; y++) {
        if (y == 4) {
            CHECK(row_is(y, only_b, 1));
        } else {
            CHECK(row_is(y, NULL, 0));
        }
    }
    CHECK(px_eq(px_at(screen, SW, 2, 3), 0, 200, 0, 255)); /* b over a */
    CHECK(px_eq(px_at(screen, SW, 2, 4), 0, 200, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 2, 10), 10, 20, 30, 255));
    CHECK(!t.bm[root].geom_dirty);

    /* a clean frame does not rebuild */
    uimk2_repaint(&t);
    CHECK(t.row_rebuilds == 2);

    /* lists that do not fit fall back to walking every item */
    give_rows(&t, root, 3);
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), true);
    uimk2_repaint(&t);
    CHECK(t.row_rebuilds == 3 && !t.bm[root].u.layout.rows_ok);
    CHECK(px_eq(px_at(screen, SW, 2, 4), 0, 200, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 31, 0), 0, 0, 200, 255));
}

/* The lists change what is walked, never the pixels: a scene of
 * overlapping half-alpha rasters renders byte-identical with and without
 * them, and with fewer samples. */
static void test_root_rows_match_linear(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[6];
    static uint8_t px[6][7 * 5 * 4];
    static uint8_t linear[SW * SH * 4];
    uint16_t root, k;
    uint32_t s_linear, s_rows;

    root = make_root(&t, items, 6);
    for (k = 0; k < 6; k++) {
        uint16_t r = make_raster(&t, 7, 5, px[k]);
        fill(px[k], 35, 40 * k, 255 - 40 * k, 17 * k, 100 + 30 * k);
        items[k].x = (int16_t)(k * 5 - 2);
        items[k].y = (int16_t)((k * 7) % 17 - 2);
        items[k].idx = r;
        t.bm[r].parent = root;
    }
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), true);
    t.samples = 0;
    uimk2_repaint(&t);
    s_linear = t.samples;
    memcpy(linear, screen, sizeof screen);

    memset(screen, SENTINEL, sizeof screen);
    give_rows(&t, root, SH * 8);
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), true);
    t.samples = 0;
    uimk2_repaint(&t);
    s_rows = t.samples;
    CHECK(memcmp(linear, screen, sizeof screen) == 0);
    CHECK(s_rows < s_linear);
}

/* ---- pack alignment and viewport crop, in pixels ----------------------- */

static void test_pack_and_viewport_pixels(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[3];
    static const uint8_t tall[1 * 4] = {255, 255, 255, 255};
    static const uint8_t shrt[1 * 2] = {255, 255};
    static const uint8_t wide[5 * 1] = {255, 255, 255, 255, 255};
    static const uint8_t narrow[2 * 1] = {255, 255};
    static uint16_t l2r_list[3], t2b_list[3];
    static uint8_t raster[6 * 6 * 4];
    uint16_t root, gt, gs, gw, gn, l2r, t2b, ras, vp;
    int x, y;

    root = make_root(&t, items, 3);
    /* L2R: a 1x4 and a 1x2 glyph with hsep 1, bottom-aligned at (0, 0) */
    gt = make_glyph(&t, 1, 4, tall);
    gs = make_glyph(&t, 1, 2, shrt);
    l2r = uimk2_bm_new(&t, UIMK2_BM_L2R);
    l2r_list[0] = gt;
    l2r_list[1] = gs;
    l2r_list[2] = 0;
    t.bm[l2r].u.pack.items = l2r_list;
    t.bm[l2r].u.pack.sep = 1;
    t.bm[gt].parent = l2r;
    t.bm[gs].parent = l2r;
    uimk2_bm_measure(&t, l2r);
    /* T2B: a 5x1 and a 2x1 glyph with vsep 1, centered at (10, 0) */
    gw = make_glyph(&t, 5, 1, wide);
    gn = make_glyph(&t, 2, 1, narrow);
    t2b = uimk2_bm_new(&t, UIMK2_BM_T2B);
    t2b_list[0] = gw;
    t2b_list[1] = gn;
    t2b_list[2] = 0;
    t.bm[t2b].u.pack.items = t2b_list;
    t.bm[t2b].u.pack.sep = 1;
    t.bm[gw].parent = t2b;
    t.bm[gn].parent = t2b;
    uimk2_bm_measure(&t, t2b);
    /* Viewport 3x2 at origin (1, 2) over a 6x6 raster, at (20, 5) */
    ras = make_raster(&t, 6, 6, raster);
    fill(raster, 36, 0, 0, 255, 255);
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = 3;
    t.bm[vp].h = 2;
    t.bm[vp].u.viewport.child = ras;
    t.bm[vp].u.viewport.ox = 1;
    t.bm[vp].u.viewport.oy = 2;
    t.bm[ras].parent = vp;

    items[0].x = 0;
    items[0].y = 0;
    items[0].idx = l2r;
    items[1].x = 10;
    items[1].y = 0;
    items[1].idx = t2b;
    items[2].x = 20;
    items[2].y = 5;
    items[2].idx = vp;
    t.bm[l2r].parent = root;
    t.bm[t2b].parent = root;
    t.bm[vp].parent = root;
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), true);
    uimk2_repaint(&t);

#define WHITE(x, y) px_eq(px_at(screen, SW, (x), (y)), 255, 255, 255, 255)
#define PAPERP(x, y) px_eq(px_at(screen, SW, (x), (y)), 10, 20, 30, 255)
    /* L2R 3x4: tall in column 0 rows 0..3; short in column 2 rows 2..3 */
    for (y = 0; y < 4; y++) {
        CHECK(WHITE(0, y));
        CHECK(PAPERP(1, y));
        CHECK(y >= 2 ? WHITE(2, y) : PAPERP(2, y));
    }
    /* T2B 5x3: wide on row 0; narrow on row 2 at x = (5 - 2) / 2 = 1 */
    for (x = 0; x < 5; x++) {
        CHECK(WHITE(10 + x, 0));
        CHECK(PAPERP(10 + x, 1));
        CHECK(x == 1 || x == 2 ? WHITE(10 + x, 2) : PAPERP(10 + x, 2));
    }
    /* Viewport: exactly its 3x2 box shows the raster; the raster's other
     * pixels around it are cropped to paper */
    for (y = 3; y < 9; y++) {
        for (x = 18; x < 26; x++) {
            int in = x >= 20 && x < 23 && y >= 5 && y < 7;
            CHECK(in ? px_eq(px_at(screen, SW, x, y), 0, 0, 255, 255)
                     : PAPERP(x, y));
        }
    }
#undef WHITE
#undef PAPERP
}

/* ---- bezel blit clip --------------------------------------------------- */

static void check_spans(uint16_t w, uint16_t h, uimk2_rect r) {
    int32_t x, y, x0, x1;
    for (y = -1; y <= h; y++) {
        bool any = uimk2_bezel_span(w, h, r, y, &x0, &x1);
        int ok = 1, seen = 0;
        for (x = -1; x <= w; x++) {
            int want = y >= r.y && y < r.y + r.h && x >= r.x &&
                       x < r.x + r.w && uimk2_bezel_visible(w, h, x, y);
            int got = any && x >= x0 && x < x1;
            seen |= want;
            ok &= want == got;
        }
        CHECK(ok && (any == (seen != 0)));
    }
}

static void test_bezel(void) {
    int32_t x0, x1;
    uimk2_rect all = R(0, 0, 360, 360);
    CHECK(!uimk2_bezel_visible(360, 360, 0, 0));
    CHECK(!uimk2_bezel_visible(360, 360, 359, 359));
    CHECK(uimk2_bezel_visible(360, 360, 180, 180));
    CHECK(uimk2_bezel_visible(360, 360, 0, 180));
    CHECK(uimk2_bezel_visible(360, 360, 359, 179));
    CHECK(!uimk2_bezel_visible(360, 360, 360, 180));
    /* the middle row is the full width; the top row is a short chord */
    CHECK(uimk2_bezel_span(360, 360, all, 180, &x0, &x1) && x0 == 0 &&
          x1 == 360);
    CHECK(uimk2_bezel_span(360, 360, all, 0, &x0, &x1) && x0 == 167 &&
          x1 == 193);
    /* a damage rect in the corner has nothing to send */
    CHECK(!uimk2_bezel_span(360, 360, R(0, 0, 40, 40), 10, &x0, &x1));
    CHECK(!uimk2_bezel_span(360, 360, R(0, 0, 0, 0), 180, &x0, &x1));
    /* every row equals the per-pixel predicate inside the rect */
    check_spans(360, 360, all);
    check_spans(360, 360, R(100, 2, 200, 50));
    check_spans(360, 360, R(-5, 170, 30, 20));
    check_spans(9, 9, R(0, 0, 9, 9));
    check_spans(10, 10, R(0, 0, 10, 10));
    check_spans(7, 5, R(0, 0, 7, 5));
    check_spans(1, 1, R(0, 0, 1, 1));
}

/* ---- color combiner --------------------------------------------------- */

enum {
    C_NONE,
    C_ZERO_R,
    C_SET_RGB,
    C_SCALE_A,
    C_CURVE_A,
    NCOMB
};

/* value bytes of the SCALE and CURVE entries are set per check */
static uimk2_combiner combs[NCOMB] = {
    {0, UIMK2_COMB_SET, {0, 0, 0, 0}},
    {UIMK2_COMB_R, UIMK2_COMB_SET, {0, 0, 0, 0}},
    {UIMK2_COMB_RGB, UIMK2_COMB_SET, {200, 100, 50, 0}},
    {UIMK2_COMB_A, UIMK2_COMB_SCALE, {0, 0, 0, 128}},
    {UIMK2_COMB_A, UIMK2_COMB_CURVE, {0, 0, 0, 128}},
};

/* alpha c through the alpha-only entry ci with value v; RGB must pass */
static int comb_alpha(uimk2_bmtab *t, uint8_t ci, int v, int c) {
    uint8_t s[4];
    s[0] = 11;
    s[1] = 22;
    s[2] = 33;
    s[3] = (uint8_t)c;
    combs[ci].value[3] = (uint8_t)v;
    uimk2_combine(t, ci, s);
    if (s[0] != 11 || s[1] != 22 || s[2] != 33) {
        return -1;
    }
    return s[3];
}

static void test_combiner_ops(void) {
    uimk2_bmtab t;
    uint8_t s[4];
    int v, c, ok;

    uimk2_bmtab_init(&t, storage, CAP);
    uimk2_bmtab_set_combiners(&t, combs, NCOMB);

    /* SET red to 0 leaves G, B, A */
    s[0] = 11;
    s[1] = 22;
    s[2] = 33;
    s[3] = 44;
    uimk2_combine(&t, C_ZERO_R, s);
    CHECK(px_eq(s, 0, 22, 33, 44));
    /* SET RGB leaves A */
    uimk2_combine(&t, C_SET_RGB, s);
    CHECK(px_eq(s, 200, 100, 50, 44));
    /* index 0 and indexes past the table are none */
    uimk2_combine(&t, C_NONE, s);
    CHECK(px_eq(s, 200, 100, 50, 44));
    uimk2_combine(&t, NCOMB, s);
    CHECK(px_eq(s, 200, 100, 50, 44));

    /* SCALE alpha: 0 stays 0 and 255 becomes v, for every v */
    ok = 1;
    for (v = 0; v < 256; v++) {
        ok &= comb_alpha(&t, C_SCALE_A, v, 0) == 0;
        ok &= comb_alpha(&t, C_SCALE_A, v, 255) == v;
    }
    CHECK(ok);
    /* rounded to nearest: c * v / 255 */
    ok = 1;
    for (v = 0; v < 256; v++) {
        for (c = 0; c < 256; c++) {
            int got = comb_alpha(&t, C_SCALE_A, v, c);
            int lo = c * v / 255;
            int want = (c * v - lo * 255) * 2 > 255 ? lo + 1 : lo;
            ok &= got == want;
        }
    }
    CHECK(ok);
    CHECK(comb_alpha(&t, C_SCALE_A, 128, 1) == 1); /* 0.502 */
    CHECK(comb_alpha(&t, C_SCALE_A, 127, 1) == 0); /* 0.498 */
    CHECK(comb_alpha(&t, C_SCALE_A, 128, 200) == 100); /* 100.39 */

    /* CURVE alpha: 0 and 255 never move, for every v */
    ok = 1;
    for (v = 0; v < 256; v++) {
        ok &= comb_alpha(&t, C_CURVE_A, v, 0) == 0;
        ok &= comb_alpha(&t, C_CURVE_A, v, 255) == 255;
    }
    CHECK(ok);
    /* v = 128 is the identity */
    ok = 1;
    for (c = 0; c < 256; c++) {
        ok &= comb_alpha(&t, C_CURVE_A, 128, c) == c;
    }
    CHECK(ok);
    /* above 128 nothing moves down, below 128 nothing moves up, and the
     * result stays in 0..255 */
    ok = 1;
    for (v = 0; v < 256; v++) {
        for (c = 0; c < 256; c++) {
            int got = comb_alpha(&t, C_CURVE_A, v, c);
            ok &= got >= 0 && got <= 255;
            ok &= v > 128 ? got >= c : (v < 128 ? got <= c : got == c);
        }
    }
    CHECK(ok);
    /* midtones move strictly */
    ok = 1;
    for (c = 64; c <= 191; c++) {
        ok &= comb_alpha(&t, C_CURVE_A, 160, c) > c;
        ok &= comb_alpha(&t, C_CURVE_A, 255, c) > c;
        ok &= comb_alpha(&t, C_CURVE_A, 96, c) < c;
        ok &= comb_alpha(&t, C_CURVE_A, 0, c) < c;
    }
    CHECK(ok);
    /* 128 + 127 * 128 * 127 / 32768 = 128 + 63.5, truncated */
    CHECK(comb_alpha(&t, C_CURVE_A, 255, 128) == 191);
    /* 128 - 128 * 128 * 127 / 32768 = 128 - 63.5, truncated toward 0 */
    CHECK(comb_alpha(&t, C_CURVE_A, 0, 128) == 65);
    /* 64 + 64 * 64 * 191 / 32768 = 64 + 23.875 */
    CHECK(comb_alpha(&t, C_CURVE_A, 192, 64) == 87);
}

/* The child's combiner applies to its samples before the blend, and the
 * child's own pixels are not changed. */
static void test_combiner_before_blend(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[2];
    static uint8_t back[2 * 2 * 4], front[2 * 2 * 4];
    uint16_t root, rb, rf;
    uint32_t before;

    root = make_root(&t, items, 0);
    uimk2_bmtab_set_combiners(&t, combs, NCOMB);
    rb = make_raster(&t, 2, 2, back);
    rf = make_raster(&t, 2, 2, front);
    fill(back, 4, 0, 0, 255, 255);
    fill(front, 4, 255, 255, 255, 255);
    items[0].x = 0;
    items[0].y = 0;
    items[0].idx = rb;
    items[1].x = 0;
    items[1].y = 0;
    items[1].idx = rf;
    t.bm[root].u.layout.n = 2;
    t.bm[rb].parent = root;
    t.bm[rf].parent = root;

    /* no combiner: the opaque white front hides the back */
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(screen, SW, 0, 0), 255, 255, 255, 255));

    /* SCALE alpha by 128: the front is half covered, the back is sampled */
    combs[C_SCALE_A].value[3] = 128;
    t.bm[rf].combiner = C_SCALE_A;
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == 8);
    CHECK(px_eq(px_at(screen, SW, 1, 1), 128, 128, 255, 255));
    CHECK(px_eq(px_at(front, 2, 1, 1), 255, 255, 255, 255));

    /* SET R to 0 on the front: cyan over blue */
    t.bm[rf].combiner = C_ZERO_R;
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(screen, SW, 0, 1), 0, 255, 255, 255));

    /* SCALE alpha by 0 on the front: only the back shows */
    combs[C_SCALE_A].value[3] = 0;
    t.bm[rf].combiner = C_SCALE_A;
    uimk2_invalidate(&t, root, R(0, 0, 2, 2), false);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(screen, SW, 1, 0), 0, 0, 255, 255));
}

/* ---- scroll and cache --------------------------------------------------- */

#define VW 6 /* scroll tests: viewport and line cache size */
#define VH 4
#define RW 12 /* backing raster size, wider than tall */
#define RH 10

/* raster pixel (x, y) = (x, y, 0, 255) */
static void fill_coords(uint8_t *px, int w, int h) {
    int x, y;
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            uint8_t *p = &px[(y * w + x) * 4];
            p[0] = (uint8_t)x;
            p[1] = (uint8_t)y;
            p[2] = 0;
            p[3] = 255;
        }
    }
}

/* The VW x VH window of px at (bx, by) shows the coordinate raster seen
 * from origin (ox, oy). */
static int window_is(const uint8_t *px, int stride, int bx, int by, int ox,
                     int oy) {
    int x, y, ok = 1;
    for (y = 0; y < VH; y++) {
        for (x = 0; x < VW; x++) {
            ok &= px_eq(px_at(px, stride, bx + x, by + y), x + ox, y + oy, 0,
                        255);
        }
    }
    return ok;
}

static int outside_is(const uint8_t *px, const uint8_t *snap, int bx, int by) {
    int x, y, ok = 1;
    for (y = 0; y < SH; y++) {
        for (x = 0; x < SW; x++) {
            if (x >= bx && x < bx + VW && y >= by && y < by + VH) {
                continue;
            }
            ok &= memcmp(px_at(px, SW, x, y), px_at(snap, SW, x, y), 4) == 0;
        }
    }
    return ok;
}

static void test_scroll_viewport_direct(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[1];
    static uint8_t raster[RW * RH * 4], snap[SW * SH * 4];
    uint16_t root, ras, vp;
    uimk2_rect blit;

    root = make_root(&t, items, 1);
    ras = make_raster(&t, RW, RH, raster);
    fill_coords(raster, RW, RH);
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = VW;
    t.bm[vp].h = VH;
    t.bm[vp].u.viewport.child = ras;
    t.bm[vp].u.viewport.ox = 2;
    t.bm[vp].u.viewport.oy = 1;
    t.bm[ras].parent = vp;
    items[0].x = 5;
    items[0].y = 3;
    items[0].idx = vp;
    t.bm[vp].parent = root;
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), false);
    uimk2_repaint(&t);
    CHECK(window_is(screen, SW, 5, 3, 2, 1));
    CHECK(px_eq(px_at(screen, SW, 4, 3), 10, 20, 30, 255)); /* paper */

    /* a mark outside the viewport that only a stray write would change */
    screen[(0 * SW + 0) * 4] = 0x77;
    memcpy(snap, screen, sizeof screen);

    /* zero scroll, and a non-viewport index, do nothing */
    uimk2_view_scroll(&t, vp, 0, 0);
    CHECK(!t.bm[vp].dirty && !t.bm[root].dirty);
    CHECK(t.bm[vp].u.viewport.ox == 2 && t.bm[vp].u.viewport.oy == 1);
    uimk2_view_scroll(&t, ras, 3, 3);
    uimk2_view_scroll(&t, root, 3, 3);
    uimk2_view_scroll(&t, 0, 3, 3);
    uimk2_view_scroll(&t, CAP - 1, 3, 3); /* past count */
    CHECK(!t.bm[vp].dirty && !t.bm[ras].dirty && !t.bm[root].dirty);
    CHECK(t.bm[vp].u.viewport.ox == 2 && t.bm[vp].u.viewport.oy == 1);

    /* a scroll adds to the origin and dirties the whole viewport box */
    uimk2_view_scroll(&t, vp, 3, 2);
    CHECK(t.bm[vp].u.viewport.ox == 5 && t.bm[vp].u.viewport.oy == 3);
    CHECK(t.bm[vp].dirty && !t.bm[vp].geom_dirty);
    CHECK(rect_eq(t.bm[vp].damage, 0, 0, VW, VH));
    CHECK(t.bm[root].dirty && rect_eq(t.bm[root].damage, 5, 3, VW, VH));
    CHECK(!t.bm[ras].dirty);
    blit = uimk2_repaint(&t);
    CHECK(rect_eq(blit, 5, 3, VW, VH));
    CHECK(window_is(screen, SW, 5, 3, 5, 3));
    CHECK(outside_is(screen, snap, 5, 3));
    CHECK(screen[0] == 0x77);

    /* negative scroll, and a scroll past the raster shows paper */
    memcpy(snap, screen, sizeof screen);
    uimk2_view_scroll(&t, vp, -5, -3);
    CHECK(t.bm[vp].u.viewport.ox == 0 && t.bm[vp].u.viewport.oy == 0);
    uimk2_repaint(&t);
    CHECK(window_is(screen, SW, 5, 3, 0, 0));
    CHECK(outside_is(screen, snap, 5, 3));
    uimk2_view_scroll(&t, vp, RW + 1, 0);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(screen, SW, 5, 3), 10, 20, 30, 255));
    CHECK(px_eq(px_at(screen, SW, 10, 6), 10, 20, 30, 255));
    CHECK(outside_is(screen, snap, 5, 3));
}

/* Sums clamp to int16; the damage is the whole box either way. */
static void test_scroll_clamp(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[1];
    static uint8_t raster[RW * RH * 4];
    uint16_t root, ras, vp;

    root = make_root(&t, items, 1);
    ras = make_raster(&t, RW, RH, raster);
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = VW;
    t.bm[vp].h = VH;
    t.bm[vp].u.viewport.child = ras;
    t.bm[ras].parent = vp;
    items[0].x = 5;
    items[0].y = 3;
    items[0].idx = vp;
    t.bm[vp].parent = root;

    t.bm[vp].u.viewport.ox = 32760;
    t.bm[vp].u.viewport.oy = -32760;
    uimk2_view_scroll(&t, vp, 100, -100);
    CHECK(t.bm[vp].u.viewport.ox == 32767 && t.bm[vp].u.viewport.oy == -32768);
    CHECK(rect_eq(t.bm[vp].damage, 0, 0, VW, VH));
    uimk2_repaint(&t);
    uimk2_view_scroll(&t, vp, 2147483647, -2147483647 - 1);
    CHECK(t.bm[vp].u.viewport.ox == 32767 && t.bm[vp].u.viewport.oy == -32768);
    CHECK(rect_eq(t.bm[vp].damage, 0, 0, VW, VH));
    uimk2_repaint(&t);
    /* only one axis moves: the other keeps its value */
    uimk2_view_scroll(&t, vp, 0, 40000);
    CHECK(t.bm[vp].u.viewport.ox == 32767 && t.bm[vp].u.viewport.oy == 7232);
    CHECK(t.bm[vp].dirty);
}

/* Scene: root -> hinted line cache (VW x VH, at (5, 3)) -> viewport ->
 * coordinate raster. Scrolling resamples the whole line and the screen
 * window, and nothing outside it. */
static void test_scroll_through_cache(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[1];
    static uint8_t raster[RW * RH * 4], cache[VW * VH * 4];
    static uint8_t snap[SW * SH * 4];
    uint16_t root, ras, vp, line;
    uimk2_rect blit;

    root = make_root(&t, items, 1);
    ras = make_raster(&t, RW, RH, raster);
    fill_coords(raster, RW, RH);
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = VW;
    t.bm[vp].h = VH;
    t.bm[vp].u.viewport.child = ras;
    t.bm[ras].parent = vp;
    line = make_raster(&t, VW, VH, cache);
    t.bm[line].u.rgba.child = vp;
    t.bm[vp].parent = line;
    items[0].x = 5;
    items[0].y = 3;
    items[0].idx = line;
    t.bm[line].parent = root;

    /* first paint: the line is dirty, so it is recomposed into its store */
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), false);
    uimk2_invalidate(&t, vp, R(0, 0, VW, VH), false);
    uimk2_repaint(&t);
    CHECK(window_is(cache, VW, 0, 0, 0, 0));
    CHECK(window_is(screen, SW, 5, 3, 0, 0));
    screen[0] = 0x77;
    memcpy(snap, screen, sizeof screen);

    uimk2_view_scroll(&t, vp, 4, 5);
    CHECK(t.bm[line].dirty && rect_eq(t.bm[line].damage, 0, 0, VW, VH));
    CHECK(rect_eq(t.bm[root].damage, 5, 3, VW, VH));
    blit = uimk2_repaint(&t);
    CHECK(rect_eq(blit, 5, 3, VW, VH));
    CHECK(window_is(cache, VW, 0, 0, 4, 5));
    CHECK(window_is(screen, SW, 5, 3, 4, 5));
    CHECK(outside_is(screen, snap, 5, 3));
    CHECK(!t.bm[line].dirty && !t.bm[vp].dirty && !t.bm[root].dirty);

    /* the line is clean again: a second scroll still redoes every pixel */
    memcpy(snap, screen, sizeof screen);
    uimk2_view_scroll(&t, vp, -1, -2);
    uimk2_repaint(&t);
    CHECK(window_is(cache, VW, 0, 0, 3, 3));
    CHECK(window_is(screen, SW, 5, 3, 3, 3));
    CHECK(outside_is(screen, snap, 5, 3));
}

/* Cache is its own kind. It stores fg composited over bg. A child
 * invalidate does not mark it. uimk2_cache_dirty does, and the bake starts
 * from bg again rather than from the bytes already in the store. */
static void test_cache_bakes_over_background(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[1];
    static uint8_t store[4 * 2 * 4], fgpx[4 * 2 * 4], bgpx[4 * 2 * 4];
    uint16_t root, cache, fg, bg;
    uint32_t before;
    int x, y;

    memset(store, 0x55, sizeof store);
    fill(bgpx, 8, 255, 0, 0, 255);
    fill(fgpx, 8, 0, 0, 0, 0);
    for (y = 0; y < 2; y++) {
        for (x = 0; x < 2; x++) {
            uint8_t *p = (uint8_t *)px_at(fgpx, 4, x, y);
            p[0] = 0;
            p[1] = 0;
            p[2] = 255;
            p[3] = 255;
        }
    }
    root = make_root(&t, items, 1);
    bg = make_raster(&t, 4, 2, bgpx);
    fg = make_raster(&t, 4, 2, fgpx);
    cache = uimk2_bm_new(&t, UIMK2_BM_CACHE);
    t.bm[cache].w = 4;
    t.bm[cache].h = 2;
    t.bm[cache].u.cache.bg = bg;
    t.bm[cache].u.cache.fg = fg;
    t.bm[cache].u.cache.px = store;
    t.bm[bg].parent = cache;
    t.bm[fg].parent = cache;
    items[0].x = 2;
    items[0].y = 2;
    items[0].idx = cache;
    t.bm[cache].parent = root;

    uimk2_cache_dirty(&t, bg);
    CHECK(!t.bm[bg].dirty);
    uimk2_cache_dirty(&t, cache);
    CHECK(t.bm[cache].dirty);
    CHECK(t.bm[root].dirty);
    before = t.samples;
    uimk2_repaint(&t);
    /* left half: fg only (4). right half: fg then bg (8). root copies 8. */
    CHECK(t.samples - before == 4 + 8 + 8);
    CHECK(!t.bm[cache].dirty);
    for (y = 0; y < 2; y++) {
        for (x = 0; x < 2; x++) {
            CHECK(px_eq(px_at(store, 4, x, y), 0, 0, 255, 255));
            CHECK(px_eq(px_at(screen, SW, 2 + x, 2 + y), 0, 0, 255, 255));
        }
        for (x = 2; x < 4; x++) {
            CHECK(px_eq(px_at(store, 4, x, y), 255, 0, 0, 255));
            CHECK(px_eq(px_at(screen, SW, 2 + x, 2 + y), 255, 0, 0, 255));
        }
    }

    /* children move; the store stays until the Cache itself is marked */
    fill(bgpx, 8, 0, 255, 0, 255);
    for (y = 0; y < 2; y++) {
        for (x = 0; x < 2; x++) {
            uint8_t *p = (uint8_t *)px_at(fgpx, 4, x, y);
            p[0] = 255;
            p[1] = 255;
            p[2] = 255;
            p[3] = 255;
        }
    }
    uimk2_invalidate(&t, fg, R(0, 0, 4, 2), false);
    CHECK(t.bm[fg].dirty);
    CHECK(!t.bm[cache].dirty);
    CHECK(!t.bm[root].dirty);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == 0);
    CHECK(px_eq(px_at(store, 4, 0, 0), 0, 0, 255, 255));
    CHECK(px_eq(px_at(store, 4, 3, 1), 255, 0, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 2, 2), 0, 0, 255, 255));

    /* a second bake reads the new bg and fg, not the previous store */
    uimk2_cache_dirty(&t, cache);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(store, 4, 0, 0), 255, 255, 255, 255));
    CHECK(px_eq(px_at(store, 4, 1, 1), 255, 255, 255, 255));
    CHECK(px_eq(px_at(store, 4, 2, 0), 0, 255, 0, 255));
    CHECK(px_eq(px_at(store, 4, 3, 1), 0, 255, 0, 255));
    CHECK(px_eq(px_at(screen, SW, 2, 2), 255, 255, 255, 255));
    CHECK(px_eq(px_at(screen, SW, 5, 3), 0, 255, 0, 255));

    /* an explicit sub-rect rebakes only that rect, from the current bg */
    bgpx[(0 * 4 + 2) * 4 + 0] = 1;
    bgpx[(0 * 4 + 2) * 4 + 1] = 2;
    bgpx[(0 * 4 + 2) * 4 + 2] = 3;
    bgpx[(0 * 4 + 2) * 4 + 3] = 255;
    uimk2_invalidate(&t, cache, R(2, 0, 1, 1), false);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(store, 4, 2, 0), 1, 2, 3, 255));
    CHECK(px_eq(px_at(store, 4, 3, 0), 0, 255, 0, 255));
    CHECK(px_eq(px_at(store, 4, 0, 0), 255, 255, 255, 255));

    /* a miss on both bg and fg stores transparent, not paper and not the
     * previous pixel */
    t.bm[cache].u.cache.bg = 0;
    t.bm[cache].u.cache.fg = 0;
    uimk2_invalidate(&t, cache, R(1, 1, 1, 1), false);
    uimk2_repaint(&t);
    CHECK(px_eq(px_at(store, 4, 1, 1), 0, 0, 0, 0));
    CHECK(px_eq(px_at(store, 4, 0, 0), 255, 255, 255, 255));
}

/* Pixel (x, y) of a w x h buffer is at index (y * w + x) * 4, in every
 * buffer the library writes: wide and tall shapes tell it from y-major. */
static void test_row_major_buffers(void) {
    uimk2_bmtab t;
    static uimk2_layout_item items[1];
    static uint8_t raster[RW * RH * 4], cache[VW * VH * 4];
    uint16_t root, ras, vp, line;
    int x, y, ok;

    root = make_root(&t, items, 1);
    ras = make_raster(&t, RW, RH, raster);
    for (y = 0; y < RH; y++) {
        for (x = 0; x < RW; x++) {
            raster[(y * RW + x) * 4 + 0] = (uint8_t)(x + 1);
            raster[(y * RW + x) * 4 + 1] = (uint8_t)(y + 1);
            raster[(y * RW + x) * 4 + 2] = (uint8_t)(y * RW + x);
            raster[(y * RW + x) * 4 + 3] = 255;
        }
    }
    vp = uimk2_bm_new(&t, UIMK2_BM_VIEWPORT);
    t.bm[vp].w = VW;
    t.bm[vp].h = VH;
    t.bm[vp].u.viewport.child = ras;
    t.bm[vp].u.viewport.ox = 3;
    t.bm[vp].u.viewport.oy = 2;
    t.bm[ras].parent = vp;
    line = make_raster(&t, VW, VH, cache);
    t.bm[line].u.rgba.child = vp;
    t.bm[vp].parent = line;
    items[0].x = 7;
    items[0].y = 5;
    items[0].idx = line;
    t.bm[line].parent = root;
    uimk2_invalidate(&t, root, R(0, 0, SW, SH), false);
    uimk2_invalidate(&t, vp, R(0, 0, VW, VH), false);
    uimk2_repaint(&t);

    ok = 1;
    for (y = 0; y < VH; y++) {
        for (x = 0; x < VW; x++) {
            int sx = x + 3, sy = y + 2;
            const uint8_t *c = &cache[(y * VW + x) * 4];
            const uint8_t *s = &screen[((5 + y) * SW + (7 + x)) * 4];
            ok &= px_eq(c, sx + 1, sy + 1, sy * RW + sx, 255);
            ok &= px_eq(s, sx + 1, sy + 1, sy * RW + sx, 255);
        }
    }
    CHECK(ok);
    /* the screen row stride is the root width, not the cache width */
    CHECK(px_eq(&screen[(5 * SW + 7) * 4], 4, 3, 2 * RW + 3, 255));
    CHECK(px_eq(&screen[(6 * SW + 7) * 4], 4, 4, 3 * RW + 3, 255));
    CHECK(px_eq(&cache[(1 * VW + 0) * 4], 4, 4, 3 * RW + 3, 255));
}

int main(void) {
    test_kinds_offsets_and_measure();
    test_kinds_sample();
    test_invalidate_walks_parents();
    test_repaint_paper_and_clean_sibling();
    test_opaque_stops_blend();
    test_root_rows();
    test_root_rows_match_linear();
    test_pack_and_viewport_pixels();
    test_bezel();
    test_combiner_ops();
    test_combiner_before_blend();
    test_scroll_viewport_direct();
    test_scroll_clamp();
    test_scroll_through_cache();
    test_cache_bakes_over_background();
    test_row_major_buffers();
    printf("test_bitmap: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
