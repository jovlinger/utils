/* phase2: k-way merge of per-shape W ranges; exteriors in first-frag order. */
#include "ta_draw_phase2.h"
#include "ta_uilayout.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

static ta_pack66_t *alloc_opaque(uint16_t w, uint16_t h) {
    ta_pack66_t *p =
        (ta_pack66_t *)malloc((size_t)w * (size_t)h * sizeof(ta_pack66_t));
    size_t i;
    ta_pack66_t ink = ta_pack66_rgba(1, 1, 1, 3);

    if (p == NULL) {
        return NULL;
    }
    for (i = 0; i < (size_t)w * (size_t)h; i++) {
        p[i] = ink;
    }
    return p;
}

static ta_phase2_frag_t g_frags[16];
static int g_nfrag;

static void rec_frag(const ta_phase2_frag_t *frag, void *ctx) {
    (void)ctx;
    if (g_nfrag < 16) {
        g_frags[g_nfrag++] = *frag;
    } else {
        g_nfrag++;
    }
}

int main(void) {
    ta_pack66_t *pa;
    ta_pack66_t *pb;
    ta_pack66_t *pc;
    ta_shape_bitmap_t a, b, c;
    ta_uilayout_t uilo[3];
    ta_draw_scene_t scene;
    ta_phase2_push_t pushes[4];
    int n;

    pa = alloc_opaque(10, 10);
    pb = alloc_opaque(10, 10);
    pc = alloc_opaque(8, 8);
    CHECK(pa != NULL && pb != NULL && pc != NULL);

    memset(&a, 0, sizeof(a));
    a.tag = TA_SHAPE_TAG_BITMAP;
    a.w = 10;
    a.h = 10;
    a.flags = ta_shape_flags_set_dirty(a.flags, 1);
    a.pixels = pa;
    memset(&b, 0, sizeof(b));
    b.tag = TA_SHAPE_TAG_BITMAP;
    b.w = 10;
    b.h = 10;
    b.flags = ta_shape_flags_set_dirty(b.flags, 1);
    b.pixels = pb;
    memset(&c, 0, sizeof(c));
    c.tag = TA_SHAPE_TAG_BITMAP;
    c.w = 8;
    c.h = 8;
    c.flags = ta_shape_flags_set_dirty(c.flags, 1);
    c.pixels = pc;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &a) == 0);
    CHECK(ta_shape_table_set(2, &b) == 0);
    CHECK(ta_shape_table_set(3, &c) == 0);

    /* Same top y: left (x=0) before right (x=5); overlap tolerated. */
    uilo[0] = ta_uilo_make(1, 5, 0, 2);
    uilo[1] = ta_uilo_make(1, 0, 0, 1);
    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 2;

    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n == 2);
    CHECK(pushes[0].shape_idx == 1 && pushes[0].exterior.x == 0);
    CHECK(pushes[1].shape_idx == 2 && pushes[1].exterior.x == 5);
    CHECK(ta_shape_flags_dirty(a.flags) == 0);
    CHECK(ta_shape_flags_dirty(b.flags) == 0);

    /* Top-down: lower y first even if scene order is bottom-first. */
    a.flags = ta_shape_flags_set_dirty(a.flags, 1);
    b.flags = ta_shape_flags_set_dirty(b.flags, 1);
    c.flags = ta_shape_flags_set_dirty(c.flags, 1);
    uilo[0] = ta_uilo_make(1, 0, 40, 1);
    uilo[1] = ta_uilo_make(1, 0, 10, 2);
    uilo[2] = ta_uilo_make(1, 0, 0, 3);
    scene.n_uilo = 3;
    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n == 3);
    CHECK(pushes[0].shape_idx == 3 && pushes[0].exterior.y == 0);
    CHECK(pushes[1].shape_idx == 2 && pushes[1].exterior.y == 10);
    CHECK(pushes[2].shape_idx == 1 && pushes[2].exterior.y == 40);

    /* Merge: two 1-row shapes, disjoint islands -> interleaved by x. */
    {
        ta_pack66_t row_a[8];
        ta_pack66_t row_b[8];
        ta_shape_bitmap_t sa, sb;

        memset(row_a, 0, sizeof(row_a));
        memset(row_b, 0, sizeof(row_b));
        row_a[0] = row_a[1] = ta_pack66_rgba(2, 0, 0, 3);
        row_b[4] = row_b[5] = ta_pack66_rgba(0, 2, 0, 3);
        memset(&sa, 0, sizeof(sa));
        sa.tag = TA_SHAPE_TAG_BITMAP;
        sa.w = 8;
        sa.h = 1;
        sa.flags = ta_shape_flags_set_rlc_n(
            ta_shape_flags_set_dirty(0, 1), 1);
        sa.pixels = row_a;
        memset(&sb, 0, sizeof(sb));
        sb.tag = TA_SHAPE_TAG_BITMAP;
        sb.w = 8;
        sb.h = 1;
        sb.flags = ta_shape_flags_set_rlc_n(
            ta_shape_flags_set_dirty(0, 1), 1);
        sb.pixels = row_b;
        CHECK(ta_shape_table_set(10, &sa) == 0);
        CHECK(ta_shape_table_set(11, &sb) == 0);
        uilo[0] = ta_uilo_make(1, 0, 0, 11); /* B island at x=4 */
        uilo[1] = ta_uilo_make(1, 0, 0, 10); /* A island at x=0 */
        scene.n_uilo = 2;
        g_nfrag = 0;
        CHECK(ta_draw_phase2_foreach_frag(&scene, rec_frag, NULL) == 0);
        CHECK(g_nfrag == 2);
        CHECK(g_frags[0].shape_idx == 10 && g_frags[0].x == 0);
        CHECK(g_frags[1].shape_idx == 11 && g_frags[1].x == 4);
    }

    free(pa);
    free(pb);
    free(pc);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_draw_phase2: %d checks ok\n", checks);
    return 0;
}
