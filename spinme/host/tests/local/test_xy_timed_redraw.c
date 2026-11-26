/*
 * local/: timed XY redraw via XYShape-only glass path (bit-identical goldens).
 * - Under veil (static): digit '4' and letter 'k', partially overlapping, fixed.
 * - Under veil (timed): digit 0..9.
 * - Veil z=3: 0x08080801 as R,G,B,A -> pack66.
 * - Over veil (timed): letter a..j, XY chosen to overlap the timed digit.
 * Glass: only ta_sd_xy_blit_glass (RLC spans + ta_sd_blend). No direct blits.
 * Goldens: screenshots/xy_timed/t00.png .. t09.png (full-file bit-identical;
 * REGEN if zlib/PNG bytes drift while RGB stays equal).
 *
 * Push-back: pack66 a2 is 0/1/2/3; a2=1 ~= 33% (nearest below a2=2 to "50%").
 */
#include "ta_draw_phase1.h"
#include "ta_glyph_bin.h"
#include "ta_pack66_png.h"
#include "ta_shape_draw.h"
#include "ta_shape_l2r.h"
#include "ta_text.h"
#include "ta_uilayout.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum {
    GLASS_W = 160,
    GLASS_H = 80,
    TIMES = 10,
    STATIC_DIGIT_X = 8,
    STATIC_DIGIT_Y = 10,
    STATIC_LETTER_X = 14,
    STATIC_LETTER_Y = 16,
    STATIC_DIGIT_CH = '4',
    STATIC_LETTER_CH = 'k',
    MOVE_DIGIT_X = 48,
    MOVE_DIGIT_Y = 18,
    MOVE_LETTER_DX = 5,
    MOVE_LETTER_DY = 6,
    VEIL_X = 0,
    VEIL_Y = 0,
    VEIL_W = 130,
    VEIL_H = 60,
    PNG_SCALE = 4,
    /* sd table: bitmaps then XY wrappers (above locked). */
    IDX_BM_STATIC_DIGIT = 200,
    IDX_BM_STATIC_LETTER = 201,
    IDX_BM_MOVE_DIGIT = 202,
    IDX_BM_MOVE_LETTER = 203,
    IDX_BM_VEIL = 204,
    IDX_XY_STATIC_DIGIT = 210,
    IDX_XY_STATIC_LETTER = 211,
    IDX_XY_MOVE_DIGIT = 212,
    IDX_XY_VEIL = 213,
    IDX_XY_MOVE_LETTER = 214
};

#define FW "../firmware/waveshare-knob-touch-lcd-1.8"
#define GLYPHS_PATH FW "/glyphs.bin"
#define GOLDEN_DIR "../screenshots/xy_timed"
#define ACTUAL_DIR "build/xy_timed"
#define VEIL_PX ta_pack66_rgba(0x08, 0x08, 0x08, 1)

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

static ta_glyph_bin_t g_gb;

static void glass_clear(ta_pack66_t *g) {
    memset(g, 0, (size_t)GLASS_W * (size_t)GLASS_H * sizeof(*g));
}

static int bake_char_into_sd(unsigned bm_idx, char ch, uint16_t *out_w,
                             uint16_t *out_h) {
    ta_shape_l2r_t line;
    char ascii[2];
    uint32_t pack[8];
    int8_t kern[8];
    ta_uilayout_t uilo;
    ta_draw_scene_t scene;
    ta_phase1_opts_t opts;
    ta_shape_bitmap_t *hdr;
    ta_sd_shape_t *bm;

    ascii[0] = ch;
    ascii[1] = '\0';
    memset(&line, 0, sizeof(line));
    if (ta_text_build(&line, ascii, &g_gb.map, g_gb.kern, pack, 8, kern, 8) !=
        0) {
        return -1;
    }
    if (ta_shape_l2r_compute_size(&line) != 0) {
        return -1;
    }
    line.pixels = (ta_pack66_t *)calloc((size_t)line.w * (size_t)line.h,
                                        sizeof(ta_pack66_t));
    if (line.pixels == NULL) {
        return -1;
    }
    line.dirty = 1;
    if (ta_shape_table_set(bm_idx, (ta_shape_bitmap_t *)(void *)&line) != 0) {
        free(line.pixels);
        return -1;
    }
    uilo = ta_uilo_make(1, 0, 0, bm_idx);
    memset(&scene, 0, sizeof(scene));
    scene.uilo = &uilo;
    scene.n_uilo = 1;
    memset(&opts, 0, sizeof(opts));
    if (ta_draw_phase1(&scene, &opts) != 0) {
        free(line.pixels);
        return -1;
    }
    hdr = ta_shape_table_get(bm_idx);
    if (hdr == NULL || hdr->pixels == NULL) {
        free(line.pixels);
        return -1;
    }
    if (ta_sd_alloc_bitmap(bm_idx, TA_SD_TAG_BITMAP, hdr->w, hdr->h) != 0) {
        free(line.pixels);
        return -1;
    }
    bm = ta_sd_get(bm_idx);
    memcpy(bm->pixels, hdr->pixels,
           (size_t)hdr->w * (size_t)hdr->h * sizeof(ta_pack66_t));
    if (out_w) {
        *out_w = hdr->w;
    }
    if (out_h) {
        *out_h = hdr->h;
    }
    (void)ta_shape_table_set(bm_idx, NULL);
    free(line.pixels);
    return 0;
}

static int make_xy(unsigned xy_idx, unsigned child_idx, int16_t x, int16_t y,
                   uint16_t w, uint16_t h) {
    ta_sd_shape_t *xy;

    if (ta_sd_alloc_bitmap(xy_idx, TA_SD_TAG_XY, w, h) != 0) {
        return -1;
    }
    xy = ta_sd_get(xy_idx);
    xy->u.xy.child = (uint16_t)child_idx;
    xy->u.xy.x = x;
    xy->u.xy.y = y;
    if (ta_sd_xy_rebuild_from_child(xy_idx) != 0) {
        return -1;
    }
    ta_sd_xy_mark_full_dirty(xy);
    return 0;
}

static void move_letter_xy(int t, int *x, int *y) {
    (void)t;
    *x = MOVE_DIGIT_X + MOVE_LETTER_DX;
    *y = MOVE_DIGIT_Y + MOVE_LETTER_DY;
}

static int refresh_xy(unsigned xy_idx, unsigned bm_idx, int16_t x, int16_t y) {
    ta_sd_shape_t *ch = ta_sd_get(bm_idx);

    if (ch == NULL) {
        return -1;
    }
    return make_xy(xy_idx, bm_idx, x, y, ch->w, ch->h);
}

static void xy_redraw(ta_pack66_t *glass, int t) {
    int ox;
    int oy;
    char digit = (char)('0' + t);
    char letter = (char)('a' + t);
    uint16_t dw = 0;
    uint16_t dh = 0;
    const unsigned order[] = {IDX_XY_STATIC_DIGIT, IDX_XY_STATIC_LETTER,
                              IDX_XY_MOVE_DIGIT, IDX_XY_VEIL,
                              IDX_XY_MOVE_LETTER};

    glass_clear(glass);

    CHECK(bake_char_into_sd(IDX_BM_MOVE_DIGIT, digit, &dw, &dh) == 0);
    CHECK(bake_char_into_sd(IDX_BM_MOVE_LETTER, letter, &dw, &dh) == 0);
    move_letter_xy(t, &ox, &oy);

    CHECK(refresh_xy(IDX_XY_MOVE_DIGIT, IDX_BM_MOVE_DIGIT,
                     (int16_t)MOVE_DIGIT_X, (int16_t)MOVE_DIGIT_Y) == 0);
    CHECK(refresh_xy(IDX_XY_MOVE_LETTER, IDX_BM_MOVE_LETTER, (int16_t)ox,
                     (int16_t)oy) == 0);
    ta_sd_xy_mark_full_dirty(ta_sd_get(IDX_XY_STATIC_DIGIT));
    ta_sd_xy_mark_full_dirty(ta_sd_get(IDX_XY_STATIC_LETTER));
    ta_sd_xy_mark_full_dirty(ta_sd_get(IDX_XY_VEIL));

    ta_sd_glass_paint_xys(glass, GLASS_W, GLASS_H, order,
                          sizeof(order) / sizeof(order[0]));
}

static int count_nonzero(const ta_pack66_t *g, int x, int y, int w, int h) {
    int yy;
    int xx;
    int n = 0;

    for (yy = 0; yy < h; yy++) {
        for (xx = 0; xx < w; xx++) {
            int dx = x + xx;
            int dy = y + yy;
            if (dx < 0 || dy < 0 || dx >= GLASS_W || dy >= GLASS_H) {
                continue;
            }
            if (g[(size_t)dy * GLASS_W + (size_t)dx] != 0) {
                n++;
            }
        }
    }
    return n;
}

static int rects_overlap(int ax, int ay, int aw, int ah, int bx, int by, int bw,
                         int bh) {
    return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
}

/* Bit-identical file compare (PNG bytes). Returns 0 if equal. */
static int files_bit_identical(const char *a, const char *b) {
    FILE *fa;
    FILE *fb;
    uint8_t ba[4096];
    uint8_t bb[4096];

    fa = fopen(a, "rb");
    fb = fopen(b, "rb");
    if (fa == NULL || fb == NULL) {
        if (fa) {
            fclose(fa);
        }
        if (fb) {
            fclose(fb);
        }
        return -1;
    }
    for (;;) {
        size_t na = fread(ba, 1, sizeof(ba), fa);
        size_t nb = fread(bb, 1, sizeof(bb), fb);
        if (na != nb || memcmp(ba, bb, na) != 0) {
            fclose(fa);
            fclose(fb);
            return -1;
        }
        if (na == 0) {
            break;
        }
    }
    fclose(fa);
    fclose(fb);
    return 0;
}

static int copy_file(const char *src, const char *dst) {
    FILE *in = fopen(src, "rb");
    FILE *out = fopen(dst, "wb");
    char buf[4096];
    size_t n;

    if (in == NULL || out == NULL) {
        if (in) {
            fclose(in);
        }
        if (out) {
            fclose(out);
        }
        return -1;
    }
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0) {
        if (fwrite(buf, 1, n, out) != n) {
            fclose(in);
            fclose(out);
            return -1;
        }
    }
    fclose(in);
    fclose(out);
    return 0;
}

int main(void) {
    ta_pack66_t *glass;
    int t;
    uint16_t sw = 0;
    uint16_t sh = 0;
    int ox0;
    int oy0;
    size_t i;

    glass = (ta_pack66_t *)calloc((size_t)GLASS_W * (size_t)GLASS_H,
                                  sizeof(*glass));
    CHECK(glass != NULL);
    CHECK(VEIL_PX == 0x01080808u);

    ta_shape_table_reset();
    ta_sd_reset();
    ta_glyph_bin_reset(&g_gb);
    CHECK(ta_glyph_bin_load(&g_gb, GLYPHS_PATH) == 0);

    CHECK(bake_char_into_sd(IDX_BM_STATIC_DIGIT, STATIC_DIGIT_CH, &sw, &sh) ==
          0);
    CHECK(make_xy(IDX_XY_STATIC_DIGIT, IDX_BM_STATIC_DIGIT,
                  (int16_t)STATIC_DIGIT_X, (int16_t)STATIC_DIGIT_Y, sw, sh) ==
          0);
    CHECK(bake_char_into_sd(IDX_BM_STATIC_LETTER, STATIC_LETTER_CH, &sw, &sh) ==
          0);
    CHECK(make_xy(IDX_XY_STATIC_LETTER, IDX_BM_STATIC_LETTER,
                  (int16_t)STATIC_LETTER_X, (int16_t)STATIC_LETTER_Y, sw,
                  sh) == 0);

    CHECK(rects_overlap(STATIC_DIGIT_X, STATIC_DIGIT_Y,
                        (int)ta_sd_get(IDX_BM_STATIC_DIGIT)->w,
                        (int)ta_sd_get(IDX_BM_STATIC_DIGIT)->h, STATIC_LETTER_X,
                        STATIC_LETTER_Y,
                        (int)ta_sd_get(IDX_BM_STATIC_LETTER)->w,
                        (int)ta_sd_get(IDX_BM_STATIC_LETTER)->h));

    CHECK(bake_char_into_sd(IDX_BM_MOVE_DIGIT, '0', &sw, &sh) == 0);
    CHECK(make_xy(IDX_XY_MOVE_DIGIT, IDX_BM_MOVE_DIGIT, (int16_t)MOVE_DIGIT_X,
                  (int16_t)MOVE_DIGIT_Y, sw, sh) == 0);
    move_letter_xy(0, &ox0, &oy0);
    CHECK(bake_char_into_sd(IDX_BM_MOVE_LETTER, 'a', &sw, &sh) == 0);
    CHECK(make_xy(IDX_XY_MOVE_LETTER, IDX_BM_MOVE_LETTER, (int16_t)ox0,
                  (int16_t)oy0, sw, sh) == 0);
    CHECK(rects_overlap(MOVE_DIGIT_X, MOVE_DIGIT_Y,
                        (int)ta_sd_get(IDX_BM_MOVE_DIGIT)->w,
                        (int)ta_sd_get(IDX_BM_MOVE_DIGIT)->h, ox0, oy0,
                        (int)ta_sd_get(IDX_BM_MOVE_LETTER)->w,
                        (int)ta_sd_get(IDX_BM_MOVE_LETTER)->h));

    /* Veil bitmap + XY. */
    CHECK(ta_sd_alloc_bitmap(IDX_BM_VEIL, TA_SD_TAG_BITMAP, VEIL_W, VEIL_H) ==
          0);
    for (i = 0; i < (size_t)VEIL_W * (size_t)VEIL_H; i++) {
        ta_sd_get(IDX_BM_VEIL)->pixels[i] = VEIL_PX;
    }
    CHECK(make_xy(IDX_XY_VEIL, IDX_BM_VEIL, (int16_t)VEIL_X, (int16_t)VEIL_Y,
                  VEIL_W, VEIL_H) == 0);

    (void)mkdir("build", 0755);
    (void)mkdir(ACTUAL_DIR, 0755);
    (void)mkdir("../screenshots", 0755);
    (void)mkdir(GOLDEN_DIR, 0755);

    for (t = 0; t < TIMES; t++) {
        int ox;
        int oy;
        char actual[160];
        char golden[160];
        const int regen = (getenv("REGEN_XY_TIMED") != NULL);

        xy_redraw(glass, t);
        move_letter_xy(t, &ox, &oy);

        CHECK(count_nonzero(glass, STATIC_DIGIT_X, STATIC_DIGIT_Y, 20,
                            (int)g_gb.text_h) > 0);
        CHECK(count_nonzero(glass, MOVE_DIGIT_X, MOVE_DIGIT_Y, 20,
                            (int)g_gb.text_h) > 0);
        CHECK(count_nonzero(glass, ox, oy, 20, (int)g_gb.text_h) > 0);
        CHECK(glass[(size_t)(GLASS_H - 1) * GLASS_W + (GLASS_W - 1)] == 0);

        snprintf(actual, sizeof(actual), ACTUAL_DIR "/t%02d.png", t);
        snprintf(golden, sizeof(golden), GOLDEN_DIR "/t%02d.png", t);
        CHECK(ta_pack66_write_png_scaled(actual, GLASS_W, GLASS_H, glass,
                                         PNG_SCALE) == 0);
        if (regen) {
            CHECK(copy_file(actual, golden) == 0);
            printf("regen %s\n", golden);
        } else if (files_bit_identical(actual, golden) == 0) {
            checks++;
            printf("bit-identical %s\n", golden);
        } else {
            checks++;
            failures++;
            fprintf(stderr, "%s:%d: PNG not bit-identical: %s vs %s\n",
                    __FILE__, __LINE__, actual, golden);
        }
    }

    {
        ta_pack66_t *a =
            (ta_pack66_t *)calloc((size_t)GLASS_W * GLASS_H, sizeof(*a));
        ta_pack66_t *b =
            (ta_pack66_t *)calloc((size_t)GLASS_W * GLASS_H, sizeof(*b));
        int x;
        int y;
        int static_same = 1;
        int move_diff = 0;

        CHECK(a != NULL && b != NULL);
        xy_redraw(a, 0);
        xy_redraw(b, 9);
        for (y = STATIC_DIGIT_Y; y < STATIC_DIGIT_Y + 28; y++) {
            for (x = STATIC_DIGIT_X; x < STATIC_DIGIT_X + 28; x++) {
                size_t ii = (size_t)y * GLASS_W + (size_t)x;
                if (a[ii] != b[ii]) {
                    static_same = 0;
                }
            }
        }
        for (y = MOVE_DIGIT_Y; y < MOVE_DIGIT_Y + 28; y++) {
            for (x = MOVE_DIGIT_X; x < MOVE_DIGIT_X + 28; x++) {
                size_t ii = (size_t)y * GLASS_W + (size_t)x;
                if (a[ii] != b[ii]) {
                    move_diff = 1;
                }
            }
        }
        CHECK(static_same == 1);
        CHECK(move_diff == 1);
        free(a);
        free(b);
    }

    ta_glyph_bin_fini(&g_gb);
    ta_sd_reset();
    free(glass);

    if (failures) {
        fprintf(stderr, "test_xy_timed_redraw: %d/%d failed\n", failures,
                checks);
        return 1;
    }
    printf("test_xy_timed_redraw: %d checks ok\n", checks);
    return 0;
}
