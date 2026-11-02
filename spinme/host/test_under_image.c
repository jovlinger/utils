/* Host: under-image invalidate rules. */
#include "ta_under_image.h"
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
    ta_shape_bitmap_t base, under, clock;
    ta_under_cache_t uc;
    ta_draw_scene_t scene;

    memset(&base, 0, sizeof(base));
    base.tag = TA_SHAPE_TAG_BITMAP;
    base.w = 8;
    base.h = 8;
    base.pixels = &px;
    memset(&under, 0, sizeof(under));
    under.tag = TA_SHAPE_TAG_BITMAP;
    under.w = 8;
    under.h = 8;
    under.pixels = &px;
    memset(&clock, 0, sizeof(clock));
    clock.tag = TA_SHAPE_TAG_BITMAP;
    clock.w = 4;
    clock.h = 2;
    clock.pixels = &px;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &base) == 0);
    CHECK(ta_shape_table_set(2, &under) == 0);
    CHECK(ta_shape_table_set(3, &clock) == 0);

    ta_under_reset(&uc);
    uc.base_shape_idx = 1;
    uc.under_shape_idx = 2;
    uc.under_valid = 1;
    memset(&scene, 0, sizeof(scene));

    /* Clock tick, box fixed: under stays clean. */
    clock.dirty = 1;
    under.dirty = 0;
    CHECK(ta_under_after_update(&uc, &scene, 3, 0) == 0);
    CHECK(under.dirty == 0);
    CHECK(uc.under_valid == 1);

    /* Base dirty: under must rebuild. */
    base.dirty = 1;
    CHECK(ta_under_after_update(&uc, &scene, 3, 0) == 1);
    CHECK(under.dirty == 1);
    CHECK(uc.under_valid == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_under_image: %d checks ok\n", checks);
    return 0;
}
