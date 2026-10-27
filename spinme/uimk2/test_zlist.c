/* Host tests for the uimk2 zlist: order, dirty, child-dirty, distant-first
 * paint, base memcpy, row diff, swap/busy, identical frame.
 *
 * The attempt-cap test prints one expected
 * "ERROR: redraw busy at attempt cap 5" line on stderr.
 */
#include "uimk2_zlist.h"

#include "uimk2_blit.h"

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

static uimk2_zlist z;
static uint8_t curr_mem[UIMK2_FRAME_BYTES];
static uint8_t next_mem[UIMK2_FRAME_BYTES];
static uint8_t base_mem[UIMK2_FRAME_BYTES];
static uimk2_ring ring;
static int pings;

static void on_ping(void *ctx) {
    int *n = ctx;
    (*n)++;
}

static void wipe_frames(void) {
    memset(curr_mem, 0, sizeof curr_mem);
    memset(next_mem, 0, sizeof next_mem);
    memset(base_mem, 0, sizeof base_mem);
    memset(&z, 0, sizeof z);
    uimk2_ring_init(&ring);
    pings = 0;
}

static bool build(const uimk2_shape_desc *d, uint16_t n) {
    return uimk2_zlist_build(&z, d, n, curr_mem, next_mem, &ring, on_ping,
                             &pings);
}

static uimk2_shape_desc solid(uint8_t sel, int x, int y, int w, int h, int r,
                              int g, int b, int a) {
    uimk2_shape_desc d;
    memset(&d, 0, sizeof d);
    d.update_selector = sel;
    d.x = (int16_t)x;
    d.y = (int16_t)y;
    d.w = (uint16_t)w;
    d.h = (uint16_t)h;
    d.rgba[0] = (uint8_t)r;
    d.rgba[1] = (uint8_t)g;
    d.rgba[2] = (uint8_t)b;
    d.rgba[3] = (uint8_t)a;
    return d;
}

static void fill_pattern(uint8_t *px) {
    uint32_t x, y;
    for (y = 0; y < PANEL_H; y++) {
        for (x = 0; x < PANEL_W; x++) {
            uint8_t *p = px + (y * PANEL_W + x) * 4u;
            p[0] = (uint8_t)x;
            p[1] = (uint8_t)y;
            p[2] = 0x40;
            p[3] = 0xFF;
        }
    }
}

static const uint8_t *pel(const uint8_t *px, uint32_t x, uint32_t y) {
    return px + (y * PANEL_W + x) * 4u;
}

static int px_is(const uint8_t *p, int r, int g, int b, int a) {
    return p[0] == r && p[1] == g && p[2] == b && p[3] == a;
}

/* Frames are pack66; compare the packed word of the RGBA sample. */
static int pack_is(const uint8_t *frame, uint32_t x, uint32_t y, int r, int g,
                   int b, int a) {
    uint8_t rgba[4];
    uint32_t want;
    const uint32_t *fb = (const uint32_t *)(const void *)frame;
    rgba[0] = (uint8_t)r;
    rgba[1] = (uint8_t)g;
    rgba[2] = (uint8_t)b;
    rgba[3] = (uint8_t)a;
    want = uimk2_blit_pack66(rgba);
    return fb[y * PANEL_W + x] == want;
}

static int is_root(uint16_t idx) {
    uint16_t i;
    for (i = 0; i < z.nroot; i++) {
        if (z.root[i] == idx) {
            return 1;
        }
    }
    return 0;
}

static int dirty_rows(void) {
    int n = 0;
    uint16_t y;
    for (y = 0; y < (uint16_t)PANEL_H; y++) {
        if (uimk2_zlist_row_dirty(&z, y)) {
            n++;
        }
    }
    return n;
}

static bool build_base_only(void) {
    uimk2_shape_desc d;
    wipe_frames();
    fill_pattern(base_mem);
    d = solid(UIMK2_UPD_FIXED, 0, 0, (int)PANEL_W, (int)PANEL_H, 0, 0, 0, 0);
    d.is_base = true;
    d.px = base_mem;
    return build(&d, 1);
}

/* Index 0 is closest. Children point down; a child is not a root.
 * A bad index or a cycle is refused and leaves the list empty. */
static void test_build_order_and_children(void) {
    uimk2_shape_desc d[4];
    uint16_t mid_kids[1];
    uint16_t root_kids[2];
    uint16_t cyc_a[1];
    uint16_t cyc_b[1];
    uint16_t bad[1];

    wipe_frames();
    d[0] = solid(UIMK2_UPD_FIXED, 1, 2, 3, 4, 0, 0, 200, 255);
    d[1] = solid(UIMK2_UPD_FIXED, 0, 0, 6, 6, 200, 0, 0, 255);
    d[2] = solid(UIMK2_UPD_FIXED, 0, 0, (int)PANEL_W, (int)PANEL_H, 0, 0, 0, 0);
    d[3] = solid(UIMK2_UPD_FIXED, 10, 10, 1, 1, 1, 1, 1, 1);
    mid_kids[0] = 0;
    root_kids[0] = 1;
    root_kids[1] = 3;
    d[1].children = mid_kids;
    d[1].nchildren = 1;
    d[2].children = root_kids;
    d[2].nchildren = 2;
    d[2].is_base = true;
    CHECK(build(d, 4));
    CHECK(z.n == 4);
    /* Slot 0 stayed the closest descriptor. */
    CHECK(z.shape[0].rgba[2] == 200);
    CHECK(z.shape[0].x == 1 && z.shape[0].y == 2);
    CHECK(z.shape[0].w == 3 && z.shape[0].h == 4);
    CHECK(z.shape[0].nchild == 0);
    CHECK(z.shape[1].nchild == 1 && z.shape[1].child[0] == 0);
    CHECK(z.shape[2].nchild == 2 && z.shape[2].child[0] == 1);
    CHECK(z.shape[2].child[1] == 3);
    CHECK(z.nroot == 1 && z.root[0] == 2);
    CHECK(!is_root(0) && !is_root(1) && !is_root(3));
    CHECK(is_root(2));

    bad[0] = 9;
    d[0] = solid(UIMK2_UPD_FIXED, 0, 0, 1, 1, 0, 0, 0, 0);
    d[0].children = bad;
    d[0].nchildren = 1;
    CHECK(!build(d, 1));
    CHECK(z.n == 0);

    d[0] = solid(UIMK2_UPD_FIXED, 0, 0, 1, 1, 0, 0, 0, 0);
    d[1] = solid(UIMK2_UPD_FIXED, 0, 0, 1, 1, 0, 0, 0, 0);
    cyc_a[0] = 1;
    cyc_b[0] = 0;
    d[0].children = cyc_a;
    d[0].nchildren = 1;
    d[1].children = cyc_b;
    d[1].nchildren = 1;
    CHECK(!build(d, 2));
    CHECK(z.n == 0);

    CHECK(!uimk2_zlist_build(&z, NULL, (uint16_t)(UIMK2_ZLIST_MAX + 1u),
                             curr_mem, next_mem, &ring, on_ping, &pings));
    CHECK(z.n == 0);
}

/* Fixed leaves dirty alone. Scroll and clocktext set it only when the
 * dynamic fields change, and neither moves the sealed exterior. Update
 * does not write pixels. */
static void test_update_dirty_sealed(void) {
    uimk2_shape_desc d;
    int16_t x, y;
    uint16_t w, h;

    wipe_frames();
    d = solid(UIMK2_UPD_FIXED, 4, 5, 6, 7, 1, 2, 3, 4);
    d.step_x = 9;
    CHECK(build(&d, 1));
    uimk2_zlist_update(&z);
    CHECK(!z.shape[0].dirty);
    CHECK(z.shape[0].ox == 0 && z.shape[0].oy == 0);
    CHECK(z.shape[0].x == 4 && z.shape[0].y == 5);

    wipe_frames();
    d = solid(UIMK2_UPD_SCROLL, 4, 5, 6, 7, 1, 2, 3, 4);
    d.step_x = 3;
    d.step_y = -1;
    CHECK(build(&d, 1));
    x = z.shape[0].x;
    y = z.shape[0].y;
    w = z.shape[0].w;
    h = z.shape[0].h;
    memset(next_mem, 0xCD, sizeof next_mem);
    uimk2_zlist_update(&z);
    CHECK(z.shape[0].dirty);
    CHECK(z.shape[0].ox == 3 && z.shape[0].oy == -1);
    CHECK(z.shape[0].x == x && z.shape[0].y == y);
    CHECK(z.shape[0].w == w && z.shape[0].h == h);
    CHECK(next_mem[0] == 0xCD);
    CHECK(next_mem[sizeof next_mem - 1] == 0xCD);
    z.shape[0].dirty = false;
    z.shape[0].step_x = 0;
    z.shape[0].step_y = 0;
    uimk2_zlist_update(&z);
    CHECK(!z.shape[0].dirty);
    CHECK(z.shape[0].ox == 3 && z.shape[0].oy == -1);

    wipe_frames();
    d = solid(UIMK2_UPD_CLOCKTEXT, 8, 9, 2, 2, 0, 0, 0, 255);
    CHECK(build(&d, 1));
    x = z.shape[0].x;
    y = z.shape[0].y;
    w = z.shape[0].w;
    h = z.shape[0].h;
    uimk2_zlist_set_clock(&z, 12, 34);
    uimk2_zlist_update(&z);
    CHECK(z.shape[0].dirty);
    CHECK(strcmp(z.shape[0].text, "12:34") == 0);
    CHECK(z.shape[0].x == x && z.shape[0].y == y);
    CHECK(z.shape[0].w == w && z.shape[0].h == h);
    z.shape[0].dirty = false;
    uimk2_zlist_update(&z);
    CHECK(!z.shape[0].dirty);
    CHECK(strcmp(z.shape[0].text, "12:34") == 0);
    uimk2_zlist_set_clock(&z, 12, 35);
    uimk2_zlist_update(&z);
    CHECK(z.shape[0].dirty);
    CHECK(strcmp(z.shape[0].text, "12:35") == 0);
    CHECK(z.shape[0].x == x && z.shape[0].w == w);
}

/* Three-level child list. Dirty climbs to the root. A clean sibling
 * stays clean. A dirty root with clean children stays dirty. */
static void test_child_dirty(void) {
    uimk2_shape_desc d[4];
    uint16_t mid_kids[1];
    uint16_t root_kids[2];

    wipe_frames();
    d[0] = solid(UIMK2_UPD_FIXED, 0, 0, 1, 1, 0, 0, 1, 255);
    d[1] = solid(UIMK2_UPD_FIXED, 0, 0, 1, 1, 0, 0, 2, 255);
    d[2] = solid(UIMK2_UPD_FIXED, 0, 0, 1, 1, 0, 0, 3, 255);
    d[3] = solid(UIMK2_UPD_FIXED, 2, 2, 1, 1, 0, 0, 4, 255);
    mid_kids[0] = 0;
    root_kids[0] = 1;
    root_kids[1] = 3;
    d[1].children = mid_kids;
    d[1].nchildren = 1;
    d[2].children = root_kids;
    d[2].nchildren = 2;
    CHECK(build(d, 4));
    CHECK(z.nroot == 1 && z.root[0] == 2);

    z.shape[0].dirty = true;
    uimk2_zlist_update(&z);
    CHECK(z.shape[0].dirty);
    CHECK(!z.shape[1].dirty && !z.shape[2].dirty);
    uimk2_zlist_mark_dirty_from_children(&z, z.root[0]);
    CHECK(z.shape[0].dirty);
    CHECK(z.shape[1].dirty);
    CHECK(z.shape[2].dirty);
    CHECK(!z.shape[3].dirty);

    z.shape[0].dirty = false;
    z.shape[1].dirty = false;
    z.shape[2].dirty = false;
    z.shape[1].dirty = true;
    uimk2_zlist_mark_dirty_from_children(&z, 2);
    CHECK(!z.shape[0].dirty);
    CHECK(z.shape[1].dirty);
    CHECK(z.shape[2].dirty);
    CHECK(!z.shape[3].dirty);

    z.shape[0].dirty = false;
    z.shape[1].dirty = false;
    z.shape[2].dirty = true;
    z.shape[3].dirty = false;
    uimk2_zlist_mark_dirty_from_children(&z, 2);
    CHECK(z.shape[2].dirty);
    CHECK(!z.shape[0].dirty && !z.shape[1].dirty && !z.shape[3].dirty);

    z.shape[0].dirty = true;
    uimk2_zlist_render(&z);
    CHECK(!z.shape[0].dirty && !z.shape[1].dirty);
    CHECK(!z.shape[2].dirty && !z.shape[3].dirty);
}

/* Base memcpy first, then distant-first. Index 0 wins the overlap.
 * Next is not cleared: a frame with no base keeps bytes outside shapes.
 * A clean shape is still painted. */
static void test_paint_order_and_base(void) {
    uimk2_shape_desc d[3];
    uint8_t pix[4];

    wipe_frames();
    fill_pattern(base_mem);
    memset(next_mem, 0xAB, sizeof next_mem);
    d[0] = solid(UIMK2_UPD_FIXED, 1, 1, 2, 2, 0, 0, 200, 255);
    d[1] = solid(UIMK2_UPD_FIXED, 0, 0, 6, 6, 200, 0, 0, 255);
    d[2] = solid(UIMK2_UPD_FIXED, 0, 0, (int)PANEL_W, (int)PANEL_H, 0, 0, 0, 0);
    d[2].is_base = true;
    d[2].px = base_mem;
    CHECK(build(d, 3));
    CHECK(z.shape[0].rgba[2] == 200);
    CHECK(z.shape[2].is_base);
    z.shape[1].dirty = true;
    CHECK(!z.shape[0].dirty);
    uimk2_zlist_render(&z);
    CHECK(pack_is(next_mem, 1, 1, 0, 0, 200, 255));
    CHECK(pack_is(next_mem, 0, 0, 200, 0, 0, 255));
    CHECK(pack_is(next_mem, 5, 5, 200, 0, 0, 255));
    CHECK(pack_is(next_mem, 100, 80, 100, 80, 0x40, 0xFF));
    CHECK(pack_is(next_mem, 6, 6, 6, 6, 0x40, 0xFF));
    CHECK(!z.shape[0].dirty && !z.shape[1].dirty && !z.shape[2].dirty);

    wipe_frames();
    memset(next_mem, 0xAB, sizeof next_mem);
    pix[0] = 1;
    pix[1] = 2;
    pix[2] = 3;
    pix[3] = 255; /* A2 != 0 so the word is paint, not a skip */
    d[0] = solid(UIMK2_UPD_FIXED, 8, 9, 1, 1, 0, 0, 0, 0);
    d[0].px = pix;
    d[1] = solid(UIMK2_UPD_FIXED, 4, 5, 1, 1, 9, 8, 7, 255);
    CHECK(build(d, 2));
    uimk2_zlist_render(&z);
    CHECK(pack_is(next_mem, 8, 9, 1, 2, 3, 255));
    CHECK(pack_is(next_mem, 4, 5, 9, 8, 7, 255));
    CHECK(px_is(pel(next_mem, 0, 0), 0xAB, 0xAB, 0xAB, 0xAB));
    CHECK(px_is(pel(next_mem, 4, 6), 0xAB, 0xAB, 0xAB, 0xAB));
    CHECK(px_is(pel(next_mem, PANEL_W - 1u, PANEL_H - 1u), 0xAB, 0xAB, 0xAB,
                0xAB));

    wipe_frames();
    memset(next_mem, 0xAB, sizeof next_mem);
    d[0] = solid(UIMK2_UPD_FIXED, 0, 0, (int)PANEL_W, (int)PANEL_H, 7, 8, 9, 255);
    d[0].is_base = true;
    CHECK(build(&d[0], 1));
    uimk2_zlist_render(&z);
    CHECK(pack_is(next_mem, 0, 0, 7, 8, 9, 255));
    CHECK(pack_is(next_mem, 50, 50, 7, 8, 9, 255));
    CHECK(pack_is(next_mem, PANEL_W - 1u, PANEL_H - 1u, 7, 8, 9, 255));
}

/* First frame swaps and sets every row bit. The same picture again
 * swaps nothing and clears the bits. One corrupted row sets one bit. */
static void test_row_diff_swap_identical(void) {
    uint8_t *front;
    uint32_t off;

    CHECK(build_base_only());
    uimk2_zlist_update_render_draw(&z);
    CHECK(z.curr == next_mem);
    CHECK(z.next == curr_mem);
    CHECK(z.busy);
    CHECK(pings == 1);
    CHECK(dirty_rows() == (int)PANEL_H);
    CHECK(uimk2_zlist_row_dirty(&z, 0));
    CHECK(uimk2_zlist_row_dirty(&z, (uint16_t)(PANEL_H - 1u)));
    CHECK(!uimk2_zlist_row_dirty(&z, (uint16_t)PANEL_H));
    CHECK(pack_is(z.curr, 100, 80, 100, 80, 0x40, 0xFF));

    front = z.curr;
    z.busy = false;
    uimk2_zlist_update_render_draw(&z);
    CHECK(z.curr == front);
    CHECK(z.next == curr_mem);
    CHECK(!z.busy);
    CHECK(pings == 1);
    CHECK(dirty_rows() == 0);
    CHECK(memcmp(z.curr, z.next, UIMK2_FRAME_BYTES) == 0);

    CHECK(build_base_only());
    uimk2_zlist_update_render_draw(&z);
    z.busy = false;
    off = (10u * PANEL_W + 4u) * 4u;
    z.curr[off] ^= 0xFFu;
    front = z.curr;
    uimk2_zlist_update_render_draw(&z);
    CHECK(dirty_rows() == 1);
    CHECK(uimk2_zlist_row_dirty(&z, 10));
    CHECK(!uimk2_zlist_row_dirty(&z, 9));
    CHECK(!uimk2_zlist_row_dirty(&z, 11));
    CHECK(z.curr != front);
    CHECK(z.busy);
    CHECK(pings == 2);
}

/* Busy skips the compare. The ring gets redraw attempt 1, and a later
 * redraw event swaps once A is free. Five busy passes log the cap. */
static void test_busy_redraw_retry(void) {
    uint8_t *front;
    uint32_t i;
    const uimk2_event *ev;

    CHECK(build_base_only());
    uimk2_zlist_update_render_draw(&z);
    CHECK(pings == 1 && z.busy);
    front = z.curr;
    base_mem[0] ^= 0xFFu;
    z.row_dirty[0] = 0x5A;
    uimk2_zlist_update_render_draw(&z);
    CHECK(z.curr == front);
    CHECK(z.busy);
    CHECK(pings == 1);
    CHECK(z.row_dirty[0] == 0x5A);
    CHECK(uimk2_ring_len(&ring) == 1);
    ev = uimk2_ring_peek(&ring);
    CHECK(ev != NULL);
    CHECK(ev->selector == UIMK2_EV_REDRAW);
    CHECK(ev->u.redraw.attempt == 1);
    CHECK(z.redraw_attempt == 1);

    z.busy = false;
    uimk2_zlist_redraw(&z, ev->u.redraw.attempt);
    CHECK(pings == 2);
    CHECK(z.busy);
    CHECK(z.curr != front);
    CHECK(z.redraw_attempt == 0);
    CHECK(uimk2_ring_len(&ring) == 1);
    CHECK(pack_is(z.curr, 0, 0, (int)base_mem[0], (int)base_mem[1],
                  (int)base_mem[2], (int)base_mem[3]));

    CHECK(build_base_only());
    z.busy = true;
    for (i = 0; i < REDRAW_ATTEMPT_CAP; i++) {
        uimk2_zlist_update_render_draw(&z);
    }
    CHECK(pings == 0);
    CHECK(z.curr == curr_mem);
    CHECK(z.busy);
    CHECK(uimk2_ring_len(&ring) == REDRAW_ATTEMPT_CAP);
    CHECK(z.redraw_attempt == (int)REDRAW_ATTEMPT_CAP);
    for (i = 0; i < REDRAW_ATTEMPT_CAP; i++) {
        ev = &ring.slot[(ring.head + i) % QUEUE_DEPTH];
        CHECK(ev->selector == UIMK2_EV_REDRAW);
        CHECK(ev->u.redraw.attempt == (int)(i + 1u));
    }
}

int main(void) {
    test_build_order_and_children();
    test_update_dirty_sealed();
    test_child_dirty();
    test_paint_order_and_base();
    test_row_diff_swap_identical();
    test_busy_redraw_retry();
    printf("test_zlist: %d checks, %d failures\n", checks, failures);
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
