/* Viewport ox scroll bakes child window; under-image buffer stays intact. */
#include "ta_uilayout.h"
#include "ta_under_image.h"
#include "ta_viewport.h"

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
    ta_pack66_t child_px[8];
    ta_pack66_t vp_px[4];
    ta_pack66_t under_px[4];
    ta_shape_bitmap_t child;
    ta_shape_bitmap_t under;
    ta_shape_viewport_t vp;
    ta_pack66_t under_before[4];
    uint8_t r, g, b, a;

    child_px[0] = ta_pack66_rgba(0x3f, 0, 0, 3);
    child_px[1] = ta_pack66_rgba(0, 0x3f, 0, 3);
    child_px[2] = ta_pack66_rgba(0, 0, 0x3f, 3);
    child_px[3] = ta_pack66_rgba(0x3f, 0x3f, 0, 3);
    memset(&child, 0, sizeof(child));
    child.tag = TA_SHAPE_TAG_BITMAP;
    child.w = 4;
    child.h = 1;
    child.pixels = child_px;

    under_px[0] = ta_pack66_rgba(1, 1, 1, 3);
    memcpy(under_before, under_px, sizeof(under_px));
    memset(&under, 0, sizeof(under));
    under.tag = TA_SHAPE_TAG_BITMAP;
    under.w = 2;
    under.h = 2;
    under.pixels = under_px;

    memset(&vp, 0, sizeof(vp));
    vp.tag = TA_SHAPE_TAG_VIEWPORT;
    vp.w = 2;
    vp.h = 1;
    vp.pixels = vp_px;
    vp.child_idx = 1;
    vp.ox = 1;
    vp.oy = 0;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &child) == 0);
    CHECK(ta_shape_table_set(2, &under) == 0);
    CHECK(ta_viewport_bake(&vp) == 0);

    ta_unpack66(vp_px[0], &r, &g, &b, &a);
    CHECK(g == 0x3f); /* child[1] after ox=1 */
    ta_unpack66(vp_px[1], &r, &g, &b, &a);
    CHECK(b == 0x3f); /* child[2] */

    CHECK(memcmp(under_px, under_before, sizeof(under_px)) == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_viewport: %d checks ok\n", checks);
    return 0;
}
