/* Glass pipeline contract: update + phase1 + phase2 + under-image together. */
#include "ta_draw_phase1.h"
#include "ta_draw_phase2.h"
#include "ta_draw_update.h"
#include "ta_under_image.h"
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

static ta_pack66_t *alloc_fill(uint16_t w, uint16_t h, ta_pack66_t ink) {
    ta_pack66_t *p =
        (ta_pack66_t *)malloc((size_t)w * (size_t)h * sizeof(ta_pack66_t));
    size_t i;

    if (p == NULL) {
        return NULL;
    }
    for (i = 0; i < (size_t)w * (size_t)h; i++) {
        p[i] = ink;
    }
    return p;
}

int main(void) {
    ta_pack66_t ink = ta_pack66_rgba(1, 2, 3, 3);
    ta_pack66_t *base_px;
    ta_pack66_t *under_px;
    ta_pack66_t *clock_px;
    ta_shape_bitmap_t base, under, clock;
    ta_uilayout_t uilo[2];
    ta_draw_node_t nodes[1];
    ta_draw_scene_t scene;
    ta_phase2_push_t pushes[4];
    ta_under_cache_t uc;
    int n;

    base_px = alloc_fill(4, 4, ink);
    under_px = alloc_fill(4, 4, ink);
    clock_px = alloc_fill(2, 1, ink);
    CHECK(base_px != NULL && under_px != NULL && clock_px != NULL);

    memset(&base, 0, sizeof(base));
    base.tag = TA_SHAPE_TAG_BITMAP;
    base.w = 4;
    base.h = 4;
    base.pixels = base_px;
    memset(&under, 0, sizeof(under));
    under.tag = TA_SHAPE_TAG_BITMAP;
    under.w = 4;
    under.h = 4;
    under.pixels = under_px;
    under.flags = ta_shape_flags_set_dirty(under.flags, 0);
    memset(&clock, 0, sizeof(clock));
    clock.tag = TA_SHAPE_TAG_BITMAP;
    clock.w = 2;
    clock.h = 1;
    clock.pixels = clock_px;

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
    clock.flags = ta_shape_flags_set_dirty(clock.flags, 1);
    CHECK(ta_under_after_update(&uc, &scene, 3, 0) == 0);
    CHECK(ta_shape_flags_dirty(under.flags) == 0);

    base.flags = ta_shape_flags_set_dirty(base.flags, 1);
    CHECK(ta_under_after_update(&uc, &scene, 3, 0) == 1);
    CHECK(ta_shape_flags_dirty(under.flags) == 1);

    uilo[0] = ta_uilo_set_dirty(uilo[0], 1);
    CHECK(ta_draw_phase1(&scene, NULL) == 0);
    n = ta_draw_phase2(&scene, pushes, 4);
    CHECK(n >= 1);

    free(base_px);
    free(under_px);
    free(clock_px);

    if (failures != 0) {
        fprintf(stderr, "test_draw_glass_contract: %d/%d failed\n", failures,
                checks);
        return 1;
    }
    printf("test_draw_glass_contract: %d checks ok (green)\n", checks);
    return 0;
}
