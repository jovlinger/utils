/* UILayout 32-bit dirty/x/y/shape word; pack66 BitMap in the shape table. */
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
    ta_uilayout_t w;
    ta_pack66_t px;
    uint8_t r, g, b, a;
    ta_pack66_t pix[4];
    ta_shape_bitmap_t bm;
    uint8_t accept_hit[TA_UILAYOUT_MAX];

    CHECK(sizeof(ta_uilayout_t) == 4);

    w = ta_uilo_make(1, 10, 20, 7);
    CHECK(ta_uilo_dirty(w) == 1);
    CHECK(ta_uilo_x(w) == 10);
    CHECK(ta_uilo_y(w) == 20);
    CHECK(ta_uilo_shape(w) == 7);
    w = ta_uilo_set_dirty(w, 0);
    CHECK(ta_uilo_dirty(w) == 0);
    CHECK(ta_uilo_shape(w) == 7);

    /* Parallel accept_hit array (documented choice). */
    memset(accept_hit, 0, sizeof(accept_hit));
    accept_hit[0] = 1;
    CHECK(accept_hit[0] == 1);

    px = ta_pack66_rgba(0x3f, 0x10, 0x01, 3);
    ta_unpack66(px, &r, &g, &b, &a);
    CHECK(r == 0x3f);
    CHECK(g == 0x10);
    CHECK(b == 0x01);
    CHECK(a == 3);

    pix[0] = ta_pack66_rgba(1, 2, 3, 3);
    pix[1] = ta_pack66_rgba(0, 0, 0, 0); /* skip */
    bm.tag = TA_SHAPE_TAG_BITMAP;
    bm.dirty = 1;
    bm.w = 2;
    bm.h = 1;
    bm.pixels = pix;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(7, &bm) == 0);
    CHECK(ta_shape_table_get(7) == &bm);
    CHECK(ta_shape_table_get(7)->w == 2);
    CHECK(ta_uilo_shape(ta_uilo_make(0, 0, 0, 7)) == 7);
    CHECK(ta_shape_table_get(ta_uilo_shape(ta_uilo_make(0, 0, 0, 7)))->pixels[0] ==
          pix[0]);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_uilayout: %d checks ok\n", checks);
    return 0;
}
