/*
 * Glass contract end-test (PLAN). Greener as update/phase1/phase2 land;
 * stays red until under-image invalidation rules are wired end-to-end.
 */
#include "ta_draw_phase1.h"
#include "ta_draw_phase2.h"
#include "ta_draw_update.h"
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
    ta_shape_bitmap_t base;
    ta_uilayout_t uilo[1];
    ta_draw_node_t nodes[1];
    ta_draw_scene_t scene;
    ta_phase2_push_t pushes[2];
    int n;

    memset(&base, 0, sizeof(base));
    base.tag = TA_SHAPE_TAG_BITMAP;
    base.w = 4;
    base.h = 4;
    base.dirty = 0;
    base.pixels = &px;
    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &base) == 0);
    uilo[0] = ta_uilo_make(0, 0, 0, 1);
    memset(nodes, 0, sizeof(nodes));
    nodes[0].shape_idx = 1;
    nodes[0].update_enum = TA_UPD_NOOP;
    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 1;
    scene.nodes = nodes;
    scene.n_nodes = 1;

    CHECK(ta_draw_update(&scene) == 0);
    base.dirty = 1;
    uilo[0] = ta_uilo_set_dirty(uilo[0], 1);
    CHECK(ta_draw_phase1(&scene, NULL) == 0);
    n = ta_draw_phase2(&scene, pushes, 2);
    CHECK(n == 1);

    /* Still RED: under-image invalidate policy not implemented as API. */
    fprintf(stderr,
            "RED remaining: under_image_invalidate (scroll/clock must not "
            "dirty under-Cache without base move)\n");
    CHECK(0); /* force red until 001e */

    if (failures != 0) {
        fprintf(stderr, "test_draw_glass_contract: %d/%d failed (red)\n",
                failures, checks);
        return 1;
    }
    return 0;
}
