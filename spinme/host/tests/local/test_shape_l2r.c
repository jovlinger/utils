/* Shapepack tag densities (6x5..3x10) and L2R width/height from children. */
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
    uint32_t words[8];
    size_t nw;
    unsigned idxs[] = {1, 2, 3};
    unsigned out[8];
    ta_pack66_t pix = ta_pack66_rgba(1, 1, 1, 3);
    ta_shape_bitmap_t a, b, c;
    ta_shape_l2r_t l2r;
    int8_t kern[] = {1, -1, 0};

    CHECK(ta_shapepack_encode(words, 8, &nw, idxs, 3, TA_PACK_TAG_3x10) == 0);
    CHECK(nw == 2); /* one data + terminator */
    CHECK(ta_shapepack_decode_word(words[0], out, 8) == 3);
    CHECK(out[0] == 1 && out[1] == 2 && out[2] == 3);
    CHECK(ta_shapepack_decode_word(words[1], out, 8) == 0);

    CHECK(ta_shapepack_encode(words, 8, &nw, idxs, 3, TA_PACK_TAG_6x5) == 0);
    CHECK(((words[0] >> 30) & 3) == TA_PACK_TAG_6x5);

    memset(&a, 0, sizeof(a));
    memset(&b, 0, sizeof(b));
    memset(&c, 0, sizeof(c));
    a.tag = TA_SHAPE_TAG_BITMAP;
    a.w = 10;
    a.h = 8;
    a.pixels = &pix;
    b.tag = TA_SHAPE_TAG_BITMAP;
    b.w = 5;
    b.h = 12;
    b.pixels = &pix;
    c.tag = TA_SHAPE_TAG_BITMAP;
    c.w = 3;
    c.h = 4;
    c.pixels = &pix;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &a) == 0);
    CHECK(ta_shape_table_set(2, &b) == 0);
    CHECK(ta_shape_table_set(3, &c) == 0);

    CHECK(ta_shapepack_encode(words, 8, &nw, idxs, 3, TA_PACK_TAG_3x10) == 0);
    memset(&l2r, 0, sizeof(l2r));
    l2r.tag = TA_SHAPE_TAG_L2R;
    l2r.pack = words;
    l2r.kernings = kern;
    l2r.n_items = 3;
    CHECK(ta_shape_l2r_compute_size(&l2r) == 0);
    /* w = 10+1 + 5-1 + 3+0 = 18; h = max(8,12,4)=12 */
    CHECK(l2r.w == 18);
    CHECK(l2r.h == 12);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_shape_l2r: %d checks ok\n", checks);
    return 0;
}
