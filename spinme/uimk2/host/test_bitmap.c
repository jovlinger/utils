#include <stdio.h>
#include <string.h>

#include "bitmap.h"

static int failures = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, \
                    #cond);                                                  \
            failures++;                                                      \
        }                                                                    \
    } while (0)

static const uint8_t PAPER[3] = {10, 20, 30};

static void put(uint8_t *buf, int w, int x, int y, uint8_t r, uint8_t g,
                uint8_t b, uint8_t a)
{
    uint8_t *p = buf + ((size_t)y * w + (size_t)x) * 4u;
    p[0] = r;
    p[1] = g;
    p[2] = b;
    p[3] = a;
}

static int is(const uint8_t *buf, int w, int x, int y, uint8_t r, uint8_t g,
              uint8_t b, uint8_t a)
{
    const uint8_t *p = buf + ((size_t)y * w + (size_t)x) * 4u;
    return p[0] == r && p[1] == g && p[2] == b && p[3] == a;
}

static void fill(uint8_t *buf, int w, int h, uint8_t r, uint8_t g, uint8_t b,
                 uint8_t a)
{
    int x, y;
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            put(buf, w, x, y, r, g, b, a);
        }
    }
}

static BmRect rect(int x, int y, int w, int h)
{
    BmRect r;
    r.x = (int16_t)x;
    r.y = (int16_t)y;
    r.w = (int16_t)w;
    r.h = (int16_t)h;
    return r;
}

static LayoutItem item(int x, int y, uint16_t idx)
{
    LayoutItem it;
    it.x = (int16_t)x;
    it.y = (int16_t)y;
    it.idx = idx;
    return it;
}

static void test_kinds_and_parents(void)
{
    BitmapTable t;
    LayoutItem root_items[4];
    LayoutItem l2r_items[1];
    uint16_t root, line, l2r, t2b, vp, glyph;
    uint16_t n = 0;

    bm_init(&t);
    root = bm_new(&t, BM_KIND_LAYOUT, 6, 4);
    line = bm_new(&t, BM_KIND_RGBA, 3, 2);
    l2r = bm_new(&t, BM_KIND_L2R, 4, 2);
    t2b = bm_new(&t, BM_KIND_T2B, 4, 4);
    vp = bm_new(&t, BM_KIND_VIEWPORT, 2, 2);
    glyph = bm_new(&t, BM_KIND_GLYPH, 3, 2);
    CHECK(root != BM_NULL && line != BM_NULL && l2r != BM_NULL);
    CHECK(t2b != BM_NULL && vp != BM_NULL && glyph != BM_NULL);
    CHECK(t.nodes[root].kind == BM_KIND_LAYOUT);
    CHECK(t.nodes[line].kind == BM_KIND_RGBA);
    CHECK(t.nodes[l2r].kind == BM_KIND_L2R);
    CHECK(t.nodes[t2b].kind == BM_KIND_T2B);
    CHECK(t.nodes[vp].kind == BM_KIND_VIEWPORT);
    CHECK(t.nodes[glyph].kind == BM_KIND_GLYPH);

    root_items[0] = item(0, 0, line);
    root_items[1] = item(0, 2, l2r);
    root_items[2] = item(3, 2, t2b);
    root_items[3] = item(0, 0, vp);
    CHECK(bm_set_children(&t, root, root_items, 4));
    l2r_items[0] = item(0, 0, glyph);
    CHECK(bm_set_children(&t, l2r, l2r_items, 1));

    CHECK(t.nodes[root].parent == BM_NULL);
    CHECK(t.nodes[line].parent == root);
    CHECK(t.nodes[l2r].parent == root);
    CHECK(t.nodes[t2b].parent == root);
    CHECK(t.nodes[vp].parent == root);
    CHECK(t.nodes[glyph].parent == l2r);

    while (bm_new(&t, BM_KIND_RGBA, 1, 1) != BM_NULL) {
        n++;
    }
    CHECK(n == BM_MAX_NODES - 1 - 6);
}

static void test_invalidate_walks_parents(void)
{
    BitmapTable t;
    LayoutItem root_items[2];
    LayoutItem a_items[1];
    LayoutItem v_items[1];
    uint16_t root, a, b, v, c;

    bm_init(&t);
    root = bm_new(&t, BM_KIND_LAYOUT, 20, 20);
    a = bm_new(&t, BM_KIND_LAYOUT, 10, 10);
    b = bm_new(&t, BM_KIND_RGBA, 3, 3);
    v = bm_new(&t, BM_KIND_VIEWPORT, 6, 6);
    c = bm_new(&t, BM_KIND_RGBA, 4, 4);
    root_items[0] = item(4, 5, a);
    root_items[1] = item(10, 0, v);
    CHECK(bm_set_children(&t, root, root_items, 2));
    a_items[0] = item(1, 2, b);
    CHECK(bm_set_children(&t, a, a_items, 1));
    bm_set_viewport_origin(&t, v, 2, 3);
    v_items[0] = item(0, 0, c);
    CHECK(bm_set_children(&t, v, v_items, 1));

    /* Layout items shift by their x, y on the way up. */
    bm_invalidate(&t, b, rect(0, 0, 1, 1), 0);
    CHECK(t.nodes[b].dirty && t.nodes[a].dirty && t.nodes[root].dirty);
    CHECK(t.nodes[b].damage.x == 0 && t.nodes[b].damage.w == 1);
    CHECK(t.nodes[a].damage.x == 1 && t.nodes[a].damage.y == 2);
    CHECK(t.nodes[root].damage.x == 5 && t.nodes[root].damage.y == 7);
    CHECK(!t.nodes[root].geom_dirty);

    /* A second damage on the same node unions with the first. */
    bm_invalidate(&t, b, rect(2, 2, 1, 1), 0);
    CHECK(t.nodes[b].damage.x == 0 && t.nodes[b].damage.y == 0);
    CHECK(t.nodes[b].damage.w == 3 && t.nodes[b].damage.h == 3);

    /* A Viewport subtracts its origin; geometry marks every ancestor. */
    bm_invalidate(&t, c, rect(3, 3, 1, 1), 1);
    CHECK(t.nodes[c].geom_dirty && t.nodes[v].geom_dirty);
    CHECK(t.nodes[root].geom_dirty);
    CHECK(!t.nodes[a].geom_dirty);
    CHECK(t.nodes[v].damage.x == 1 && t.nodes[v].damage.y == 0);
    CHECK(t.nodes[root].damage.x == 5 && t.nodes[root].damage.y == 0);
    CHECK(t.nodes[root].damage.w == 7 && t.nodes[root].damage.h == 10);
}

static void test_repaint_paper_and_clean_sibling(void)
{
    BitmapTable t;
    LayoutItem items[2];
    uint8_t screen[6 * 4 * 4];
    uint8_t left_px[3 * 2 * 4];
    uint8_t right_px[3 * 2 * 4];
    uint16_t root, left, right;

    bm_init(&t);
    root = bm_new(&t, BM_KIND_LAYOUT, 6, 4);
    left = bm_new(&t, BM_KIND_RGBA, 3, 2);
    right = bm_new(&t, BM_KIND_RGBA, 3, 2);
    bm_set_owner(&t, root, screen, PAPER);
    bm_set_owner(&t, left, left_px, PAPER);
    bm_set_owner(&t, right, right_px, PAPER);
    items[0] = item(0, 0, left);
    items[1] = item(3, 0, right);
    CHECK(bm_set_children(&t, root, items, 2));

    fill(left_px, 3, 2, 200, 0, 0, 255);
    fill(right_px, 3, 2, 0, 200, 0, 255);
    fill(screen, 6, 4, 0, 0, 0, 0);
    bm_invalidate(&t, root, rect(0, 0, 6, 4), 1);
    bm_repaint(&t, root);
    CHECK(!t.nodes[root].dirty && !t.nodes[root].geom_dirty);
    CHECK(is(screen, 6, 0, 0, 200, 0, 0, 255));
    CHECK(is(screen, 6, 2, 1, 200, 0, 0, 255));
    CHECK(is(screen, 6, 3, 0, 0, 200, 0, 255));
    CHECK(is(screen, 6, 5, 1, 0, 200, 0, 255));
    CHECK(is(screen, 6, 0, 2, PAPER[0], PAPER[1], PAPER[2], 255));
    CHECK(is(screen, 6, 5, 3, PAPER[0], PAPER[1], PAPER[2], 255));

    /* Only the right line is damaged. The left line's root pixels must not
     * be written, so a sentinel placed over them survives the repaint. */
    fill(screen, 6, 4, 1, 1, 1, 255);
    fill(right_px, 3, 2, 0, 0, 200, 255);
    bm_invalidate(&t, root, rect(3, 0, 3, 2), 0);
    bm_repaint(&t, root);
    CHECK(is(screen, 6, 0, 0, 1, 1, 1, 255));
    CHECK(is(screen, 6, 2, 1, 1, 1, 1, 255));
    CHECK(is(screen, 6, 3, 0, 0, 0, 200, 255));
    CHECK(is(screen, 6, 5, 1, 0, 0, 200, 255));

    /* A damage rect over pixels no child covers writes paper. */
    bm_invalidate(&t, root, rect(4, 2, 2, 2), 0);
    bm_repaint(&t, root);
    CHECK(is(screen, 6, 4, 2, PAPER[0], PAPER[1], PAPER[2], 255));
    CHECK(is(screen, 6, 5, 3, PAPER[0], PAPER[1], PAPER[2], 255));
    CHECK(is(screen, 6, 0, 0, 1, 1, 1, 255));
}

static void test_opaque_stops_blend(void)
{
    BitmapTable t;
    LayoutItem items[2];
    uint8_t screen[4 * 2 * 4];
    uint8_t front_px[2 * 2 * 4];
    uint8_t behind_px[4 * 2 * 4];
    uint16_t root, front, behind;

    bm_init(&t);
    root = bm_new(&t, BM_KIND_LAYOUT, 4, 2);
    front = bm_new(&t, BM_KIND_RGBA, 2, 2);
    behind = bm_new(&t, BM_KIND_RGBA, 4, 2);
    bm_set_owner(&t, root, screen, PAPER);
    bm_set_owner(&t, front, front_px, PAPER);
    bm_set_owner(&t, behind, behind_px, PAPER);
    items[0] = item(0, 0, front);
    items[1] = item(0, 0, behind);
    CHECK(bm_set_children(&t, root, items, 2));

    /* Opaque front: 4 front samples, then the 4 pixels it does not cover
     * sample the behind node once each. The behind node is never sampled
     * under the opaque front. */
    fill(front_px, 2, 2, 255, 0, 0, 255);
    fill(behind_px, 4, 2, 0, 0, 255, 255);
    bm_invalidate(&t, root, rect(0, 0, 4, 2), 1);
    t.child_samples = 0;
    bm_repaint(&t, root);
    CHECK(t.child_samples == 8);
    CHECK(is(screen, 4, 0, 0, 255, 0, 0, 255));
    CHECK(is(screen, 4, 1, 1, 255, 0, 0, 255));
    CHECK(is(screen, 4, 3, 1, 0, 0, 255, 255));

    /* Half-transparent front: both layers are sampled under it.
     * Front weight 128, behind weight 127, straight color (128, 0, 127). */
    fill(front_px, 2, 2, 255, 0, 0, 128);
    bm_invalidate(&t, root, rect(0, 0, 4, 2), 0);
    t.child_samples = 0;
    bm_repaint(&t, root);
    CHECK(t.child_samples == 12);
    CHECK(is(screen, 4, 0, 0, 128, 0, 127, 255));
    CHECK(is(screen, 4, 3, 1, 0, 0, 255, 255));
}

static void test_viewport_crop(void)
{
    BitmapTable t;
    LayoutItem root_items[1];
    LayoutItem v_items[1];
    uint8_t screen[2 * 2 * 4];
    uint8_t child_px[4 * 4 * 4];
    uint16_t root, v, c;
    int x, y;

    bm_init(&t);
    root = bm_new(&t, BM_KIND_LAYOUT, 2, 2);
    v = bm_new(&t, BM_KIND_VIEWPORT, 2, 2);
    c = bm_new(&t, BM_KIND_RGBA, 4, 4);
    bm_set_owner(&t, root, screen, PAPER);
    bm_set_owner(&t, c, child_px, PAPER);
    bm_set_viewport_origin(&t, v, 1, 1);
    root_items[0] = item(0, 0, v);
    v_items[0] = item(0, 0, c);
    CHECK(bm_set_children(&t, root, root_items, 1));
    CHECK(bm_set_children(&t, v, v_items, 1));
    for (y = 0; y < 4; y++) {
        for (x = 0; x < 4; x++) {
            put(child_px, 4, x, y, (uint8_t)(x * 10), (uint8_t)(y * 10), 0,
                255);
        }
    }

    /* The viewport samples the child at (x + 1, y + 1). */
    bm_invalidate(&t, root, rect(0, 0, 2, 2), 1);
    bm_repaint(&t, root);
    CHECK(is(screen, 2, 0, 0, 10, 10, 0, 255));
    CHECK(is(screen, 2, 1, 1, 20, 20, 0, 255));
}

int main(void)
{
    test_kinds_and_parents();
    test_invalidate_walks_parents();
    test_repaint_paper_and_clean_sibling();
    test_opaque_stops_blend();
    test_viewport_crop();

    if (failures) {
        fprintf(stderr, "test_bitmap: %d check(s) failed\n", failures);
        return 1;
    }
    printf("test_bitmap: all checks passed\n");
    return 0;
}
