/* Host: phase2 whole exteriors + coverage cull; clears dirty. */
#include "ta_draw_phase2.h"
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
    ta_pack66_t px = ta_pack66_rgba(1, 1, 1, 3);
    ta_shape_bitmap_t lo, hi;
    ta_uilayout_t uilo[2];
    ta_draw_scene_t scene;
    ta_phase2_push_t pushes[4];
    int n;

    memset(&lo, 0, sizeof(lo));
    lo.tag = TA_SHAPE_TAG_BITMAP;
    lo.w = 10;
    lo.h = 10;
    lo.dirty = 1;
    lo.pixels = &px;
    memset(&hi, 0, sizeof(hi));
    hi.tag = TA_SHAPE_TAG_BITMAP;
    hi.w = 10;
    hi.h = 10;
    hi.dirty = 1;
    hi.pixels = &px;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &lo) == 0);
    CHECK(ta_shape_table_set(2, &hi) == 0);

    /* Same exterior: nearer (idx1) covers farther (idx0). */
    uilo[0] = ta_uilo_make(1, 0, 0, 1);
    uilo[1] = ta_uilo_make(1, 0, 0, 2);

    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 2;

    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n == 1);
    CHECK(pushes[0].shape_idx == 2);
    CHECK(pushes[0].exterior.w == 10);
    CHECK(hi.dirty == 0);
    CHECK(lo.dirty == 1); /* culled; still dirty but not pushed */
    CHECK(ta_uilo_dirty(uilo[1]) == 0);
    CHECK(ta_uilo_dirty(uilo[0]) == 1);

    /* Partial overlap: both push. */
    lo.dirty = 1;
    hi.dirty = 1;
    uilo[0] = ta_uilo_make(1, 0, 0, 1);
    uilo[1] = ta_uilo_make(1, 5, 5, 2);
    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n == 2);
    CHECK(pushes[0].shape_idx == 2);
    CHECK(pushes[1].shape_idx == 1);
    CHECK(lo.dirty == 0 && hi.dirty == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_draw_phase2: %d checks ok\n", checks);
    return 0;
}
