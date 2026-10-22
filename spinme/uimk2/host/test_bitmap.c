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

static LayoutItem child_at(const BitmapTable *t, uint16_t parent, int i)
{
    return t->items[t->nodes[parent].first_item + i];
}

static void test_l2r_bottom_aligns(void)
{
    BitmapTable t;
    LayoutItem items[3];
    uint16_t line, a, b, c;

    bm_init(&t);
    line = bm_new(&t, BM_KIND_L2R, 0, 0);
    a = bm_new(&t, BM_KIND_RGBA, 2, 1);
    b = bm_new(&t, BM_KIND_RGBA, 3, 3);
    c = bm_new(&t, BM_KIND_RGBA, 1, 2);
    items[0] = item(0, 0, a);
    items[1] = item(0, 0, b);
    items[2] = item(0, 0, c);
    CHECK(bm_set_children(&t, line, items, 3));
    bm_set_sep(&t, line, 1);
    bm_layout(&t, line);

    /* Width is the child widths plus one sep between each pair; height is
     * the tallest child. Every child's bottom edge sits on the same row. */
    CHECK(t.nodes[line].w == 8 && t.nodes[line].h == 3);
    CHECK(child_at(&t, line, 0).x == 0 && child_at(&t, line, 0).y == 2);
    CHECK(child_at(&t, line, 1).x == 3 && child_at(&t, line, 1).y == 0);
    CHECK(child_at(&t, line, 2).x == 7 && child_at(&t, line, 2).y == 1);

    bm_set_sep(&t, line, 0);
    bm_layout(&t, line);
    CHECK(t.nodes[line].w == 6 && t.nodes[line].h == 3);
    CHECK(child_at(&t, line, 1).x == 2 && child_at(&t, line, 2).x == 5);
}

static void test_t2b_centers_cross_axis(void)
{
    BitmapTable t;
    LayoutItem items[3];
    uint16_t col, a, b, c;

    bm_init(&t);
    col = bm_new(&t, BM_KIND_T2B, 0, 0);
    a = bm_new(&t, BM_KIND_RGBA, 2, 1);
    b = bm_new(&t, BM_KIND_RGBA, 4, 2);
    c = bm_new(&t, BM_KIND_RGBA, 3, 1);
    items[0] = item(0, 0, a);
    items[1] = item(0, 0, b);
    items[2] = item(0, 0, c);
    CHECK(bm_set_children(&t, col, items, 3));
    bm_set_sep(&t, col, 1);
    bm_layout(&t, col);

    /* Height is the child heights plus seps; width is the widest child.
     * Each child is centred on the cross axis, rounding down on odd gaps. */
    CHECK(t.nodes[col].w == 4 && t.nodes[col].h == 6);
    CHECK(child_at(&t, col, 0).x == 1 && child_at(&t, col, 0).y == 0);
    CHECK(child_at(&t, col, 1).x == 0 && child_at(&t, col, 1).y == 2);
    CHECK(child_at(&t, col, 2).x == 0 && child_at(&t, col, 2).y == 5);
}

static void test_nested_layout_and_empty(void)
{
    BitmapTable t;
    LayoutItem outer_items[2];
    LayoutItem inner_items[2];
    uint16_t outer, inner, r, a, b, empty;

    bm_init(&t);
    outer = bm_new(&t, BM_KIND_L2R, 0, 0);
    inner = bm_new(&t, BM_KIND_T2B, 0, 0);
    r = bm_new(&t, BM_KIND_RGBA, 2, 2);
    a = bm_new(&t, BM_KIND_RGBA, 2, 1);
    b = bm_new(&t, BM_KIND_RGBA, 4, 2);
    outer_items[0] = item(0, 0, inner);
    outer_items[1] = item(0, 0, r);
    CHECK(bm_set_children(&t, outer, outer_items, 2));
    inner_items[0] = item(0, 0, a);
    inner_items[1] = item(0, 0, b);
    CHECK(bm_set_children(&t, inner, inner_items, 2));
    bm_layout(&t, outer);

    /* The inner column is laid out first, so the outer line sees its size. */
    CHECK(t.nodes[inner].w == 4 && t.nodes[inner].h == 3);
    CHECK(t.nodes[outer].w == 6 && t.nodes[outer].h == 3);
    CHECK(child_at(&t, outer, 0).x == 0 && child_at(&t, outer, 0).y == 0);
    CHECK(child_at(&t, outer, 1).x == 4 && child_at(&t, outer, 1).y == 1);
    CHECK(child_at(&t, inner, 0).x == 1 && child_at(&t, inner, 0).y == 0);
    CHECK(child_at(&t, inner, 1).x == 0 && child_at(&t, inner, 1).y == 1);

    empty = bm_new(&t, BM_KIND_L2R, 9, 9);
    bm_layout(&t, empty);
    CHECK(t.nodes[empty].w == 0 && t.nodes[empty].h == 0);
}

static void test_root_rows_rebuild_on_geometry(void)
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

    /* The first geometry repaint builds the per-row lists. */
    bm_invalidate(&t, root, rect(0, 0, 6, 4), 1);
    bm_repaint(&t, root);
    CHECK(t.row_builds == 1 && t.row_valid && t.row_owner == root);
    CHECK(t.row_off[1] - t.row_off[0] == 2);
    CHECK(t.row_off[3] - t.row_off[2] == 0);

    /* Content-only damage does not rebuild the lists. */
    fill(right_px, 3, 2, 0, 0, 200, 255);
    bm_invalidate(&t, root, rect(3, 0, 3, 2), 0);
    bm_repaint(&t, root);
    CHECK(t.row_builds == 1);
    CHECK(is(screen, 6, 3, 0, 0, 0, 200, 255));

    /* Moving the right line down to row 2 with geometry rebuilds the lists,
     * so row 2 now lists it and the repaint shows it there. */
    t.items[t.nodes[root].first_item + 1].y = 2;
    bm_invalidate(&t, root, rect(0, 0, 6, 4), 1);
    bm_repaint(&t, root);
    CHECK(t.row_builds == 2);
    CHECK(t.row_off[3] - t.row_off[2] == 1);
    CHECK(is(screen, 6, 3, 0, PAPER[0], PAPER[1], PAPER[2], 255));
    CHECK(is(screen, 6, 3, 2, 0, 0, 200, 255));
    CHECK(is(screen, 6, 0, 0, 200, 0, 0, 255));
}

static void test_viewport_clips_to_its_rect(void)
{
    BitmapTable t;
    LayoutItem root_items[1];
    LayoutItem v_items[1];
    uint8_t screen[3 * 3 * 4];
    uint8_t child_px[4 * 4 * 4];
    uint16_t root, v, c;
    int x, y;

    bm_init(&t);
    root = bm_new(&t, BM_KIND_LAYOUT, 3, 3);
    v = bm_new(&t, BM_KIND_VIEWPORT, 2, 2);
    c = bm_new(&t, BM_KIND_RGBA, 4, 4);
    bm_set_owner(&t, root, screen, PAPER);
    bm_set_owner(&t, c, child_px, PAPER);
    bm_set_viewport_origin(&t, v, 2, 2);
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

    /* The 2x2 viewport samples child (2..3, 2..3). Pixels outside its rect
     * are not covered by it and take paper. */
    bm_invalidate(&t, root, rect(0, 0, 3, 3), 1);
    bm_repaint(&t, root);
    CHECK(is(screen, 3, 0, 0, 20, 20, 0, 255));
    CHECK(is(screen, 3, 1, 1, 30, 30, 0, 255));
    CHECK(is(screen, 3, 2, 0, PAPER[0], PAPER[1], PAPER[2], 255));
    CHECK(is(screen, 3, 0, 2, PAPER[0], PAPER[1], PAPER[2], 255));
}

static void test_bezel_span(void)
{
    int x0 = -1, x1 = -1;
    int y;

    /* Size 8: pixel centres inside a radius-4 circle. */
    CHECK(bm_bezel_span(8, 0, &x0, &x1) && x0 == 2 && x1 == 5);
    CHECK(bm_bezel_span(8, 3, &x0, &x1) && x0 == 0 && x1 == 7);
    CHECK(bm_bezel_span(8, 7, &x0, &x1) && x0 == 2 && x1 == 5);
    CHECK(!bm_bezel_span(8, 8, &x0, &x1));
    CHECK(!bm_bezel_span(8, -1, &x0, &x1));

    /* The device round panel: 360 across. */
    CHECK(bm_bezel_span(360, 0, &x0, &x1) && x0 == 167 && x1 == 192);
    CHECK(bm_bezel_span(360, 180, &x0, &x1) && x0 == 0 && x1 == 359);

    /* The circle is symmetric top to bottom and left to right. */
    for (y = 0; y < 360; y++) {
        int a0 = -1, a1 = -1, b0 = -1, b1 = -1;
        CHECK(bm_bezel_span(360, y, &a0, &a1));
        CHECK(bm_bezel_span(360, 359 - y, &b0, &b1));
        CHECK(a0 == b0 && a1 == b1);
        CHECK(a0 + a1 == 359);
    }
}

int main(void)
{
    test_kinds_and_parents();
    test_invalidate_walks_parents();
    test_repaint_paper_and_clean_sibling();
    test_opaque_stops_blend();
    test_viewport_crop();
    test_l2r_bottom_aligns();
    test_t2b_centers_cross_axis();
    test_nested_layout_and_empty();
    test_root_rows_rebuild_on_geometry();
    test_viewport_clips_to_its_rect();
    test_bezel_span();

    if (failures) {
        fprintf(stderr, "test_bitmap: %d check(s) failed\n", failures);
        return 1;
    }
    printf("test_bitmap: all checks passed\n");
    return 0;
}
