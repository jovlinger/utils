/*
 * Glass contract end-test (PLAN). Green when update/phase1/phase2/under-image
 * rules hold together.
 */
#include "ta_draw_phase1.h"
#include "ta_draw_phase2.h"
#include "ta_draw_update.h"
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
    ta_pack66_t px = ta_pack66_rgba(1, 2, 3, 3);
    ta_shape_bitmap_t base, under, clock;
    ta_uilayout_t uilo[2];
    ta_draw_node_t nodes[1];
    ta_draw_scene_t scene;
    ta_phase2_push_t pushes[4];
    ta_under_cache_t uc;
    int n;

    memset(&base, 0, sizeof(base));
    base.tag = TA_SHAPE_TAG_BITMAP;
    base.w = 4;
    base.h = 4;
    base.pixels = &px;
    memset(&under, 0, sizeof(under));
    under.tag = TA_SHAPE_TAG_BITMAP;
    under.w = 4;
    under.h = 4;
    under.pixels = &px;
    under.dirty = 0;
    memset(&clock, 0, sizeof(clock));
    clock.tag = TA_SHAPE_TAG_BITMAP;
    clock.w = 2;
    clock.h = 1;
    clock.pixels = &px;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &base) == 0);
    CHECK(ta_shape_table_set(2, &under) == 0);
    CHECK(ta_shape_table_set(3, &clock) == 0);

    uilo[0] = ta_uilo_make(0, 0, 0, 1);
    uilo[1] = ta_uilo_make(0, 1, 1, 3);
    memset(nodes, 0, sizeof(nodes));
    nodes[0].shape_idx = 3;
    nodes[0].update_enum = TA_UPD_NOOP;
    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 2;
    scene.nodes = nodes;
    scene.n_nodes = 1;

    CHECK(ta_draw_update(&scene) == 0);

    ta_under_reset(&uc);
    uc.base_shape_idx = 1;
    uc.under_shape_idx = 2;
    uc.under_valid = 1;
    clock.dirty = 1;
    CHECK(ta_under_after_update(&uc, &scene, 3, 0) == 0);
    CHECK(under.dirty == 0);

    base.dirty = 1;
    CHECK(ta_under_after_update(&uc, &scene, 3, 0) == 1);
    CHECK(under.dirty == 1);

    uilo[0] = ta_uilo_set_dirty(uilo[0], 1);
    CHECK(ta_draw_phase1(&scene, NULL) == 0);
    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n >= 1);

    if (failures != 0) {
        fprintf(stderr, "test_draw_glass_contract: %d/%d failed\n", failures,
                checks);
        return 1;
    }
    printf("test_draw_glass_contract: %d checks ok (green)\n", checks);
    return 0;
}
