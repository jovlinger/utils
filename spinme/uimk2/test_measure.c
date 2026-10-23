/* Measurement for a later scroll optimization.
 *
 * The redraw path stays row-major. This file records two facts:
 * an x-scroll memmove of a row-major buffer is one copy per row, while
 * the same shift of a y-major buffer is one contiguous copy; and a clean
 * Cache blit samples fewer children than rebaking a stack.
 * Times are printed. They do not select a winner inside the library.
 */
#include "uimk2_bitmap.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static int failures;
static int checks;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,  \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

#define CAP 16
#define W 64
#define H 48
#define LAYERS 6
#define REPS 80

static uimk2_bm storage[CAP];
static uint8_t screen[W * H * 4];
static uint8_t cache[W * H * 4];
static uint8_t layer[LAYERS][W * H * 4];
static const uint8_t PAPER[4] = {0, 0, 0, 255};

static uimk2_rect box(int x, int y, int w, int h) {
    uimk2_rect r;
    r.x = (int16_t)x;
    r.y = (int16_t)y;
    r.w = (uint16_t)w;
    r.h = (uint16_t)h;
    return r;
}

static uint64_t nsec(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

/* Destination span of an x-shift that keeps (w - dx) pixels on each row.
 * Row-major rows are split by the discarded columns. Y-major columns of
 * the retained width are one interval.
 */
static void test_scroll_copy_spans(void) {
    const int w = 8;
    const int h = 4;
    const int dx = 3;
    const int row_bytes = (w - dx) * 4;
    const int retained = h * (w - dx) * 4;
    int y;
    int split = 1;
    int cover;

    for (y = 0; y < h - 1; y++) {
        int end = (y * w + (w - dx)) * 4;
        int next = ((y + 1) * w) * 4;
        split = split && (next - end) == dx * 4;
    }
    CHECK(split);
    CHECK(row_bytes * h == retained);

    /* One memcpy from the first retained byte through the last one also
     * copies the gaps between rows. */
    cover = ((h - 1) * w + (w - dx)) * 4;
    CHECK(cover - retained == (h - 1) * dx * 4);
    CHECK(cover > retained);

    /* Y-major: column x occupies h pixels at index x * h. Retained
     * columns [0, w - dx) are the single interval [0, (w - dx) * h). */
    CHECK((w - dx) * h * 4 == retained);
    CHECK(dx * h * 4 > 0);
}

static void fill_layer(uint8_t *px, int n, int tag) {
    int i;
    for (i = 0; i < n; i++) {
        px[i * 4 + 0] = (uint8_t)tag;
        px[i * 4 + 1] = 0;
        px[i * 4 + 2] = 0;
        px[i * 4 + 3] = 40;
    }
}

static void build(uimk2_bmtab *t, uimk2_layout_item *root_items,
                  uimk2_layout_item *kids) {
    uint16_t root, node, stack, c;
    int i;
    uimk2_bmtab_init(t, storage, CAP);
    memset(screen, 0xee, sizeof screen);
    memset(cache, 0x55, sizeof cache);
    root = uimk2_bm_new(t, UIMK2_BM_LAYOUT);
    t->root = root;
    t->bm[root].w = W;
    t->bm[root].h = H;
    t->bm[root].u.layout.items = root_items;
    t->bm[root].u.layout.n = 1;
    t->bm[root].u.layout.px = screen;
    memcpy(t->bm[root].u.layout.paper, PAPER, 4);
    stack = uimk2_bm_new(t, UIMK2_BM_LAYOUT);
    t->bm[stack].w = W;
    t->bm[stack].h = H;
    t->bm[stack].u.layout.items = kids;
    t->bm[stack].u.layout.n = LAYERS;
    node = uimk2_bm_new(t, UIMK2_BM_CACHE);
    t->bm[node].w = W;
    t->bm[node].h = H;
    t->bm[node].u.cache.fg = stack;
    t->bm[node].u.cache.px = cache;
    t->bm[node].parent = root;
    t->bm[stack].parent = node;
    root_items[0].x = 0;
    root_items[0].y = 0;
    root_items[0].idx = node;
    for (i = 0; i < LAYERS; i++) {
        fill_layer(layer[i], W * H, i + 1);
        c = uimk2_bm_new(t, UIMK2_BM_RGBA);
        t->bm[c].w = W;
        t->bm[c].h = H;
        t->bm[c].u.rgba.px = layer[i];
        t->bm[c].parent = stack;
        kids[i].x = 0;
        kids[i].y = 0;
        kids[i].idx = c;
    }
}

static void test_cache_versus_redraw(void) {
    uimk2_bmtab t;
    static uimk2_layout_item root_items[1];
    static uimk2_layout_item kids[LAYERS];
    uint16_t node;
    uint8_t fresh[W * H * 4];
    uint64_t t0, t1;
    uint32_t before;
    int i;
    const int area = W * H;
    const int small = 8 * 8;

    build(&t, root_items, kids);
    node = root_items[0].idx;

    uimk2_cache_dirty(&t, node);
    before = t.samples;
    uimk2_repaint(&t);
    /* bake samples the stack, the stack samples each layer, the root
     * samples the store */
    CHECK(t.samples - before == (uint32_t)((LAYERS + 2) * area));
    memcpy(fresh, screen, sizeof screen);

    /* Clean Cache: the root copies the store and does not descend. */
    uimk2_invalidate(&t, t.root, box(0, 0, W, H), false);
    CHECK(!t.bm[node].dirty);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == (uint32_t)area);
    CHECK(memcmp(screen, fresh, sizeof screen) == 0);

    t0 = nsec();
    for (i = 0; i < REPS; i++) {
        uimk2_invalidate(&t, t.root, box(0, 0, W, H), false);
        uimk2_repaint(&t);
    }
    t1 = nsec();
    printf("cache blit %dx%d x%d: %llu ns/repaint\n", W, H, REPS,
           (unsigned long long)((t1 - t0) / (uint64_t)REPS));

    t0 = nsec();
    for (i = 0; i < REPS; i++) {
        uimk2_cache_dirty(&t, node);
        uimk2_repaint(&t);
    }
    t1 = nsec();
    printf("redraw %d layers %dx%d x%d: %llu ns/repaint\n", LAYERS, W, H, REPS,
           (unsigned long long)((t1 - t0) / (uint64_t)REPS));
    CHECK(memcmp(screen, fresh, sizeof screen) == 0);

    uimk2_invalidate(&t, t.root, box(0, 0, 8, 8), false);
    before = t.samples;
    uimk2_repaint(&t);
    CHECK(t.samples - before == (uint32_t)small);

    t0 = nsec();
    for (i = 0; i < REPS; i++) {
        uimk2_invalidate(&t, t.root, box(0, 0, 8, 8), false);
        uimk2_repaint(&t);
    }
    t1 = nsec();
    printf("cache blit 8x8 x%d: %llu ns/repaint\n", REPS,
           (unsigned long long)((t1 - t0) / (uint64_t)REPS));

    t0 = nsec();
    for (i = 0; i < REPS; i++) {
        uimk2_invalidate(&t, node, box(0, 0, 8, 8), false);
        uimk2_repaint(&t);
    }
    t1 = nsec();
    printf("redraw %d layers 8x8 x%d: %llu ns/repaint\n", LAYERS, REPS,
           (unsigned long long)((t1 - t0) / (uint64_t)REPS));
}

int main(void) {
    test_scroll_copy_spans();
    test_cache_versus_redraw();
    printf("test_measure: %d checks, %d failures\n", checks, failures);
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
