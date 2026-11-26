/* ta_text_build turns ASCII+glyph map into a ShapeL2R pack+kern stream. */
#include "ta_text.h"
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
    ta_glyph_map_t glyphs;
    ta_pack66_t pix = ta_pack66_rgba(7, 7, 7, 3);
    ta_shape_bitmap_t ga, gb;
    ta_shape_l2r_t l2r;
    uint32_t pack[8];
    int8_t kern[8];
    int8_t ktab[95];

    memset(&ga, 0, sizeof(ga));
    memset(&gb, 0, sizeof(gb));
    ga.tag = TA_SHAPE_TAG_BITMAP;
    ga.w = 6;
    ga.h = 10;
    ga.pixels = &pix;
    gb.tag = TA_SHAPE_TAG_BITMAP;
    gb.w = 4;
    gb.h = 10;
    gb.pixels = &pix;

    ta_shape_table_reset();
    CHECK(ta_shape_table_set(1, &ga) == 0);
    CHECK(ta_shape_table_set(2, &gb) == 0);

    ta_glyph_map_clear(&glyphs);
    CHECK(ta_glyph_map_set(&glyphs, 'a', 1) == 0);
    CHECK(ta_glyph_map_set(&glyphs, 'b', 2) == 0);

    memset(ktab, 0, sizeof(ktab));
    ktab['a' - 32] = 1;

    CHECK(ta_text_build(&l2r, "ab", &glyphs, ktab, pack, 8, kern, 8) == 0);
    CHECK(l2r.tag == TA_SHAPE_TAG_L2R);
    CHECK(l2r.n_items == 2);
    CHECK(l2r.w == (uint16_t)(6 + 1 + 4)); /* a + kern(a) + b */
    CHECK(l2r.h == 10);
    CHECK(kern[0] == 1);
    CHECK(kern[1] == 0);

    CHECK(ta_text_build(&l2r, "ax", &glyphs, NULL, pack, 8, kern, 8) == -1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_text: %d checks ok\n", checks);
    return 0;
}
