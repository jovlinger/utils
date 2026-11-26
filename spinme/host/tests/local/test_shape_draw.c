/* Shape-draw reshape: refs, additive a2, XY RLC, locked GC. */
#include "ta_shape_draw.h"

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

static int g_push_n;
static int g_push_h[16];
static int g_push_y[16];

static void rec_push(int x, int y, int w, int h, const ta_pack66_t *px,
                     int stride_px, void *ctx) {
    (void)x;
    (void)w;
    (void)px;
    (void)stride_px;
    (void)ctx;
    if (g_push_n < 16) {
        g_push_h[g_push_n] = h;
        g_push_y[g_push_n] = y;
    }
    g_push_n++;
}

int main(void) {
    unsigned a, b, c;
    ta_pack66_t add;
    ta_pack66_t base;
    ta_pack66_t out;
    ta_sd_shape_t *xy;
    ta_pack66_t old4[4];
    ta_pack66_t new4[4];
    ta_sd_rlc_word_t *rlc;
    uint8_t off[8];
    uint8_t len[8];
    int n;

    ta_sd_reset();

    CHECK(ta_sd_pack3(1, 2, 3) == ((3u << 30) | (1u << 20) | (2u << 10) | 3u));
    ta_sd_unpack3(ta_sd_pack3(10, 20, 30), &a, &b, &c);
    CHECK(a == 10 && b == 20 && c == 30);

    /* Transparent zero. */
    CHECK(ta_sd_blend(ta_sd_word(1, 2, 3, 3), 0u) == ta_sd_word(1, 2, 3, 3));

    /* Additive a2==0: 0x0f0f0f00 as R,G,B,A bytes => word 0x000f0f0f. */
    add = ta_sd_word(0x0f, 0x0f, 0x0f, 0);
    CHECK(add == 0x000f0f0fu);
    base = ta_sd_word(0x30, 0x30, 0x30, 3);
    out = ta_sd_blend(base, add);
    {
        uint8_t r, g, b, aa;
        ta_unpack66(out, &r, &g, &b, &aa);
        CHECK(r == 0x3f && g == 0x3f && b == 0x3f && aa == 3); /* clamp */
    }

    /* a2=1 src-over still blends. */
    out = ta_sd_blend(ta_sd_word(0, 0, 0x3f, 3), ta_sd_word(0x3f, 0, 0, 1));
    CHECK(out != 0);

    CHECK(ta_sd_alloc_bitmap(200, TA_SD_TAG_XY, 2, 2) == 0);
    xy = ta_sd_get(200);
    CHECK(xy != NULL && xy->tag == TA_SD_TAG_XY && xy->pixels != NULL);
    rlc = ta_sd_xy_rlc(xy);
    CHECK(rlc != NULL);

    old4[0] = ta_sd_word(1, 0, 0, 3);
    old4[1] = ta_sd_word(1, 0, 0, 3);
    old4[2] = ta_sd_word(1, 0, 0, 3);
    old4[3] = ta_sd_word(1, 0, 0, 3);
    new4[0] = ta_sd_word(2, 0, 0, 3);
    new4[1] = old4[1];
    new4[2] = ta_sd_word(3, 0, 0, 3);
    new4[3] = old4[3];
    memcpy(xy->pixels, new4, sizeof(new4));
    ta_sd_xy_derive_rlc(xy, old4, new4);
    /* Row0 changed px0 only -> one range; row1 changed px0 only. */
    CHECK(rlc[0] != 0 || rlc[1] != 0);

    off[0] = 0;
    len[0] = 2;
    off[1] = 3;
    len[1] = 1;
    off[2] = 10;
    len[2] = 2;
    off[3] = 20;
    len[3] = 2;
    off[4] = 40;
    len[4] = 2;
    n = ta_sd_rlc_merge_to_n(off, len, 5, 4);
    CHECK(n == 4);

    /* Result: full-dirty XY blends onto glass (only XY reaches glass). */
    {
        ta_pack66_t glass[4];
        unsigned order[1];

        memset(glass, 0, sizeof(glass));
        CHECK(ta_sd_alloc_bitmap(201, TA_SD_TAG_BITMAP, 2, 2) == 0);
        ta_sd_get(201)->pixels[0] = ta_sd_word(0x10, 0, 0, 3);
        ta_sd_get(201)->pixels[1] = 0;
        ta_sd_get(201)->pixels[2] = 0;
        ta_sd_get(201)->pixels[3] = ta_sd_word(0, 0x10, 0, 3);
        CHECK(ta_sd_alloc_bitmap(202, TA_SD_TAG_XY, 2, 2) == 0);
        ta_sd_get(202)->u.xy.child = 201;
        ta_sd_get(202)->u.xy.x = 0;
        ta_sd_get(202)->u.xy.y = 0;
        CHECK(ta_sd_xy_rebuild_from_child(202) == 0);
        ta_sd_xy_mark_full_dirty(ta_sd_get(202));
        order[0] = 202;
        ta_sd_glass_paint_xys(glass, 2, 2, order, 1);
        CHECK(glass[0] == ta_sd_word(0x10, 0, 0, 3));
        CHECK(glass[3] == ta_sd_word(0, 0x10, 0, 3));
        CHECK(glass[1] == 0 && glass[2] == 0);
    }

    /* Mechanism: each dirty RLC range is one h=1 push (per raster). */
    {
        int spans;
        int i;

        g_push_n = 0;
        CHECK(ta_sd_alloc_bitmap(203, TA_SD_TAG_XY, 4, 3) == 0);
        ta_sd_get(203)->u.xy.x = 1;
        ta_sd_get(203)->u.xy.y = 2;
        ta_sd_xy_mark_full_dirty(ta_sd_get(203));
        spans = ta_sd_xy_push_dirty(203, rec_push, NULL);
        CHECK(spans == 3);
        CHECK(g_push_n == 3);
        for (i = 0; i < 3; i++) {
            CHECK(g_push_h[i] == 1);
            CHECK(g_push_y[i] == 2 + i);
        }
    }

    /* GC: locked glyph slot survives; unmarked high slot freed. */
    CHECK(ta_sd_alloc_bitmap(5, TA_SD_TAG_BITMAP, 1, 1) == 0);
    CHECK(ta_sd_alloc_bitmap(300, TA_SD_TAG_BITMAP, 1, 1) == 0);
    CHECK(ta_sd_alloc_bitmap(301, TA_SD_TAG_COMPOSITE, 1, 1) == 0);
    ta_sd_get(301)->u.composite.refs = ta_sd_pack3(300, 0, 0);
    CHECK(ta_sd_gc(301) == 0);
    CHECK(ta_sd_get(5)->tag == TA_SD_TAG_BITMAP); /* locked */
    /* Compacted out of 300/301 into first free above locked. */
    CHECK(ta_sd_get(300)->tag == TA_SD_TAG_NONE);
    CHECK(ta_sd_get(301)->tag == TA_SD_TAG_NONE);
    CHECK(ta_sd_get(TA_SD_LOCKED_MAX + 1)->tag != TA_SD_TAG_NONE);
    CHECK(ta_sd_get(200)->tag == TA_SD_TAG_NONE); /* unmarked XY freed */

    ta_sd_reset();
    if (failures) {
        fprintf(stderr, "test_shape_draw: %d/%d failed\n", failures, checks);
        return 1;
    }
    printf("test_shape_draw: %d checks ok\n", checks);
    return 0;
}
