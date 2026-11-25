/* RLC badness: transparent px in combined spans + unused slots. */
#include "ta_shape_draw.h"
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
    ta_sd_shape_t *xy;
    ta_pack66_t glass[8];
    unsigned order[1];
    char report[256];

    ta_sd_reset();
    CHECK(ta_sd_alloc_bitmap(10, TA_SD_TAG_XY, 8, 1) == 0);
    xy = ta_sd_get(10);
    CHECK(xy != NULL);
    CHECK(ta_sd_rlc_n(xy) == TA_SD_RLC_N);
    CHECK(ta_sd_rlc_max_ranges(xy) == 4u);

    /* Two opaque blobs with a transparent gap; force merge to 1 range. */
    memset(xy->pixels, 0, (size_t)xy->w * sizeof(ta_pack66_t));
    xy->pixels[0] = ta_sd_word(10, 0, 0, 3);
    xy->pixels[1] = ta_sd_word(10, 0, 0, 3);
    /* 2,3 transparent */
    xy->pixels[4] = ta_sd_word(0, 10, 0, 3);
    xy->pixels[5] = ta_sd_word(0, 10, 0, 3);

    {
        ta_pack66_t old[8];
        memset(old, 0, sizeof(old));
        /* five dirty islands -> merge down to 4 max, then we force max 1 */
        ta_sd_xy_derive_rlc(xy, old, xy->pixels);
    }

    /* Manually set one merged span covering full width (overflow case). */
    {
        uint8_t off[1] = {0};
        uint8_t len[1] = {4}; /* 8 px in /2 units */
        ta_sd_rlc_set_ranges(ta_sd_xy_rlc(xy), ta_sd_rlc_n(xy), off, len, 1);
    }

    memset(glass, 0, sizeof(glass));
    xy->u.xy.x = 0;
    xy->u.xy.y = 0;
    order[0] = 10;
    ta_sd_glass_paint_xys(glass, 8, 1, order, 1);

    CHECK(xy->badness_paints == 1);
    /* h=1: mean-per-line == totals. Transparent in span: 2,3,6,7 => 4 */
    CHECK(ta_sd_badness_overflow(xy) > 3.9f &&
          ta_sd_badness_overflow(xy) < 4.1f);
    /* max_ranges 4, used 1 => slack 3 per line */
    CHECK(ta_sd_badness_slack(xy) > 2.9f && ta_sd_badness_slack(xy) < 3.1f);
    /* combined = 4 + 8*3 = 28 */
    CHECK(ta_sd_badness_combined(xy) > 27.9f &&
          ta_sd_badness_combined(xy) < 28.1f);

    CHECK(ta_sd_format_badness_report(report, sizeof(report)) > 0);
    CHECK(strstr(report, "ov/line=4") != NULL);
    CHECK(strstr(report, "bad/line=28") != NULL);

    /* Per-shape rlc_n via alloc_bitmap_rlc. */
    CHECK(ta_sd_alloc_bitmap_rlc(11, TA_SD_TAG_XY, 4, 2, 3) == 0);
    CHECK(ta_sd_rlc_n(ta_sd_get(11)) == 3u);
    CHECK(ta_sd_rlc_max_ranges(ta_sd_get(11)) == 6u);

    /* Optimize: solid bar -> N=1; three far islands -> N=2 (lambda=8). */
    {
        ta_pack66_t row[26];
        unsigned n;
        ta_pack66_t ink = ta_sd_word(1, 0, 0, 3);

        memset(row, 0, sizeof(row));
        row[0] = row[1] = row[2] = row[3] = ink;
        n = ta_sd_optimize_rlc_n(row, 4, 1, 1u, 4u);
        CHECK(n == 1u);
        /* Even-aligned islands, gaps of 10; N=1 ov=10 vs N=2 bad=8. */
        memset(row, 0, sizeof(row));
        row[0] = row[1] = ink;
        row[12] = row[13] = ink;
        row[24] = row[25] = ink;
        n = ta_sd_optimize_rlc_n(row, 26, 1, 1u, 4u);
        CHECK(n == 2u);
    }

    if (failures != 0) {
        fprintf(stderr, "test_rlc_badness: %d/%d checks failed\n", failures,
                checks);
        return 1;
    }
    printf("test_rlc_badness: %d checks ok\n", checks);
    return 0;
}
