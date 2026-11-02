/* Host: Draw.update defs+dirty; pixmap bytes unchanged; shadow propagate. */
#include "ta_draw_update.h"
#include "ta_shape_l2r.h"
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
    ta_pack66_t glyph_px = ta_pack66_rgba(2, 2, 2, 3);
    ta_pack66_t clock_px[8];
    ta_pack66_t clock_px_before[8];
    ta_shape_bitmap_t digits[10];
    ta_shape_bitmap_t chrome;
    uint32_t clock_pack[8];
    ta_shape_l2r_t clock;
    ta_uilayout_t uilo[2];
    unsigned shadow[] = {20}; /* chrome higher than clock */
    ta_draw_node_t nodes[2];
    ta_draw_scene_t scene;
    int d;

    memset(clock_px, 0x5a, sizeof(clock_px));
    memcpy(clock_px_before, clock_px, sizeof(clock_px));

    ta_shape_table_reset();
    for (d = 0; d < 10; d++) {
        memset(&digits[d], 0, sizeof(digits[d]));
        digits[d].tag = TA_SHAPE_TAG_BITMAP;
        digits[d].w = 4;
        digits[d].h = 8;
        digits[d].pixels = &glyph_px;
        CHECK(ta_shape_table_set((unsigned)(d + 1), &digits[d]) == 0);
    }

    memset(&chrome, 0, sizeof(chrome));
    chrome.tag = TA_SHAPE_TAG_BITMAP;
    chrome.w = 40;
    chrome.h = 40;
    chrome.dirty = 0;
    chrome.pixels = &glyph_px;
    CHECK(ta_shape_table_set(20, &chrome) == 0);

    memset(&clock, 0, sizeof(clock));
    clock.tag = TA_SHAPE_TAG_L2R;
    clock.dirty = 0;
    clock.pack = clock_pack;
    clock.pixels = clock_px;
    CHECK(ta_shape_table_set(10, (ta_shape_bitmap_t *)(void *)&clock) == 0);

    uilo[0] = ta_uilo_make(0, 0, 0, 10);  /* clock */
    uilo[1] = ta_uilo_make(0, 0, 0, 20);  /* chrome */

    memset(nodes, 0, sizeof(nodes));
    nodes[0].shape_idx = 10;
    nodes[0].update_enum = TA_UPD_REPRESENT_TIME;
    nodes[0].shadow_higher = shadow;
    nodes[0].shadow_n = 1;
    nodes[1].shape_idx = 20;
    nodes[1].update_enum = TA_UPD_NOOP;

    memset(&scene, 0, sizeof(scene));
    scene.uilo = uilo;
    scene.n_uilo = 2;
    scene.nodes = nodes;
    scene.n_nodes = 2;
    for (d = 0; d < 10; d++) {
        scene.digit_glyph[d] = (unsigned)(d + 1);
    }
    memcpy(scene.clock_hhmmss, "12:34:56", 9);

    CHECK(ta_draw_update(&scene) == 0);
    CHECK(clock.dirty == 1);
    CHECK(chrome.dirty == 1);
    CHECK(ta_uilo_dirty(uilo[0]) == 1);
    CHECK(ta_uilo_dirty(uilo[1]) == 1);
    CHECK(memcmp(clock_px, clock_px_before, sizeof(clock_px)) == 0);
    CHECK(clock.pixels == clock_px);
    CHECK(clock.n_items == 8);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_draw_update: %d checks ok\n", checks);
    return 0;
}
