/* Host: SwapShape selects one of n same-size children. */
#include "ta_draw_phase1.h"
#include "ta_draw_phase2.h"
#include "ta_shape_swap.h"
#include "ta_uilayout.h"

#include <stdio.h>
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

int main(void) {
    ta_pack66_t px_a[4];
    ta_pack66_t px_b[4];
    ta_shape_bitmap_t a, b;
    ta_shape_swap_t swap;
    ta_draw_scene_t scene;
    ta_uilayout_t uilo[1];
    ta_phase2_push_t pushes[4];
    int n;

    memset(px_a, 0, sizeof(px_a));
    memset(px_b, 0, sizeof(px_b));
    px_a[0] = ta_pack66_rgba(1, 0, 0, 3);
    px_b[0] = ta_pack66_rgba(0, 1, 0, 3);

    a.tag = TA_SHAPE_TAG_BITMAP;
    a.dirty = 0;
    a.w = 2;
    a.h = 2;
    a.pixels = px_a;
    b.tag = TA_SHAPE_TAG_BITMAP;
    b.dirty = 0;
    b.w = 2;
    b.h = 2;
    b.pixels = px_b;

    memset(&swap, 0, sizeof(swap));
    swap.tag = TA_SHAPE_TAG_SWAP;
    swap.dirty = 1;
    swap.n = 2;
    swap.active = 0;
    swap.child_idx[0] = 1;
    swap.child_idx[1] = 2;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &a) == 0);
    CHECK(ta_shape_table_set(2, &b) == 0);
    CHECK(ta_shape_table_set(3, (ta_shape_bitmap_t *)(void *)&swap) == 0);
    CHECK(ta_shape_swap_bind(&swap) == 0);
    CHECK(swap.w == 2 && swap.h == 2);
    CHECK(swap.pixels == px_a);
    CHECK(ta_shape_swap_active_idx(&swap) == 1);

    CHECK(ta_shape_swap_set_active(&swap, 1) == 0);
    CHECK(swap.pixels == px_b);
    CHECK(ta_shape_swap_active_idx(&swap) == 2);
    CHECK(ta_shape_swap_set_active(&swap, 2) == -1);

    /* Mismatched child size rejected. */
    b.w = 3;
    CHECK(ta_shape_swap_bind(&swap) == -1);
    b.w = 2;
    CHECK(ta_shape_swap_set_active(&swap, 0) == 0);
    CHECK(swap.pixels == px_a);

    /* phase1 + phase2: only the swap (active child pixels) is pushed. */
    swap.dirty = 1;
    uilo[0] = ta_uilo_make(1, 0, 0, 3);
    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 1;
    CHECK(ta_draw_phase1(&scene, NULL) == 0);
    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n == 1);
    CHECK(pushes[0].shape_idx == 3);
    CHECK(swap.pixels == px_a);
    CHECK(swap.dirty == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_shape_swap: %d checks ok\n", checks);
    return 0;
}
