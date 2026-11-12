/*
 * Timed XY redraw with overlap:
 * - Under veil (static): digit '4' and letter 'k', partially overlapping, fixed.
 * - Under veil (timed): digit 0..9.
 * - Veil z=3: 0x08080801 as R,G,B,A -> pack66.
 * - Over veil (timed): letter a..j, XY chosen to overlap the timed digit.
 *
 * Push-back: pack66 a2 is 0/1/2/3; a2=1 ~= 33% (nearest below a2=2 to "50%").
 */
#include "ta_draw_phase1.h"
#include "ta_glyph_bin.h"
#include "ta_pack66_png.h"
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
    /* Static under-veil pair (do not change with t); partial overlap. */
    STATIC_DIGIT_X = 8,
    STATIC_DIGIT_Y = 10,
    STATIC_LETTER_X = 14, /* ~half glyph overlap with digit */
    STATIC_LETTER_Y = 16,
    STATIC_DIGIT_CH = '4',
    STATIC_LETTER_CH = 'k',
    /* Timed digit under veil; timed letter over veil overlaps it. */
    MOVE_DIGIT_X = 48,
    MOVE_DIGIT_Y = 18,
    MOVE_LETTER_DX = 5, /* partial overlap with timed digit */
    MOVE_LETTER_DY = 6,
    VEIL_X = 0,
    VEIL_Y = 0,
    VEIL_W = 130,
    VEIL_H = 60,
    PNG_SCALE = 4,
    IDX_STATIC_DIGIT = 900,
    IDX_STATIC_LETTER = 901,
    IDX_MOVE_DIGIT = 902,
    IDX_MOVE_LETTER = 903
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

typedef struct {
    ta_pack66_t *px;
    size_t cap;
    uint16_t w;
    uint16_t h;
} baked_glyph_t;

static baked_glyph_t g_static_digit;
static baked_glyph_t g_static_letter;
static baked_glyph_t g_move_digit;
static baked_glyph_t g_move_letter;

static void glass_clear(ta_pack66_t *g) {
    memset(g, 0, (size_t)GLASS_W * (size_t)GLASS_H * sizeof(*g));
}

static void blit_solid_rect(ta_pack66_t *dst, int ox, int oy, int w, int h,
                            ta_pack66_t px) {
    ta_shape_bitmap_t bmp;
    ta_pack66_t *row;
    int i;

    row = (ta_pack66_t *)malloc((size_t)w * (size_t)h * sizeof(*row));
    CHECK(row != NULL);
    if (row == NULL) {
        return;
    }
    for (i = 0; i < w * h; i++) {
        row[i] = px;
    }
    memset(&bmp, 0, sizeof(bmp));
    bmp.tag = TA_SHAPE_TAG_BITMAP;
    bmp.w = (uint16_t)w;
    bmp.h = (uint16_t)h;
    bmp.pixels = row;
    ta_draw_blit_bitmap(dst, GLASS_W, GLASS_H, ox, oy, &bmp);
    free(row);
}

static void blit_baked(ta_pack66_t *dst, int ox, int oy, const baked_glyph_t *g) {
    ta_shape_bitmap_t bmp;

    memset(&bmp, 0, sizeof(bmp));
    bmp.tag = TA_SHAPE_TAG_BITMAP;
    bmp.w = g->w;
    bmp.h = g->h;
    bmp.pixels = g->px;
    ta_draw_blit_bitmap(dst, GLASS_W, GLASS_H, ox, oy, &bmp);
}

static int bake_char(baked_glyph_t *slot, unsigned table_idx, char ch) {
    ta_shape_l2r_t line;
    char ascii[2];
    uint32_t pack[8];
    int8_t kern[8];
    size_t need;

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
    need = (size_t)line.w * (size_t)line.h;
    if (need == 0) {
        return -1;
    }
    if (slot->px == NULL || slot->cap < need) {
        ta_pack66_t *npx =
            (ta_pack66_t *)realloc(slot->px, need * sizeof(ta_pack66_t));
        if (npx == NULL) {
            return -1;
        }
        slot->px = npx;
        slot->cap = need;
    }
    memset(slot->px, 0, need * sizeof(ta_pack66_t));
    line.pixels = slot->px;
    line.dirty = 1;
    if (ta_shape_table_set(table_idx, (ta_shape_bitmap_t *)(void *)&line) !=
        0) {
        return -1;
    }
    {
        ta_uilayout_t uilo = ta_uilo_make(1, 0, 0, table_idx);
        ta_draw_scene_t scene;
        ta_phase1_opts_t opts;

        memset(&scene, 0, sizeof(scene));
        scene.uilo = &uilo;
        scene.n_uilo = 1;
        memset(&opts, 0, sizeof(opts));
        if (ta_draw_phase1(&scene, &opts) != 0) {
            return -1;
        }
    }
    slot->w = line.w;
    slot->h = line.h;
    return 0;
}

static void move_letter_xy(int t, int *x, int *y) {
    (void)t;
    *x = MOVE_DIGIT_X + MOVE_LETTER_DX;
    *y = MOVE_DIGIT_Y + MOVE_LETTER_DY;
}

static void xy_redraw(ta_pack66_t *glass, int t) {
    int ox;
    int oy;
    char digit = (char)('0' + t);
    char letter = (char)('a' + t);

    glass_clear(glass);

    /* z~5 under: static digit+letter (partial overlap), never change. */
    blit_baked(glass, STATIC_DIGIT_X, STATIC_DIGIT_Y, &g_static_digit);
    blit_baked(glass, STATIC_LETTER_X, STATIC_LETTER_Y, &g_static_letter);

    /* z~5 under: timed digit 0..9. */
    CHECK(bake_char(&g_move_digit, IDX_MOVE_DIGIT, digit) == 0);
    blit_baked(glass, MOVE_DIGIT_X, MOVE_DIGIT_Y, &g_move_digit);

    /* z=3 veil. */
    blit_solid_rect(glass, VEIL_X, VEIL_Y, VEIL_W, VEIL_H, VEIL_PX);

    /* z=1 over: timed letter a..j overlapping the timed digit. */
    move_letter_xy(t, &ox, &oy);
    CHECK(bake_char(&g_move_letter, IDX_MOVE_LETTER, letter) == 0);
    blit_baked(glass, ox, oy, &g_move_letter);
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
    FILE *in;
    FILE *out;
    uint8_t buf[4096];
    size_t n;

    in = fopen(src, "rb");
    if (in == NULL) {
        return -1;
    }
    out = fopen(dst, "wb");
    if (out == NULL) {
        fclose(in);
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
    int ox0;
    int oy0;

    glass = (ta_pack66_t *)calloc((size_t)GLASS_W * (size_t)GLASS_H,
                                  sizeof(*glass));
    CHECK(glass != NULL);
    CHECK(VEIL_PX == 0x01080808u);

    ta_shape_table_reset();
    ta_glyph_bin_reset(&g_gb);
    CHECK(ta_glyph_bin_load(&g_gb, GLYPHS_PATH) == 0);

    CHECK(bake_char(&g_static_digit, IDX_STATIC_DIGIT, STATIC_DIGIT_CH) == 0);
    CHECK(bake_char(&g_static_letter, IDX_STATIC_LETTER, STATIC_LETTER_CH) ==
          0);
    CHECK(rects_overlap(STATIC_DIGIT_X, STATIC_DIGIT_Y, (int)g_static_digit.w,
                        (int)g_static_digit.h, STATIC_LETTER_X, STATIC_LETTER_Y,
                        (int)g_static_letter.w, (int)g_static_letter.h));

    move_letter_xy(0, &ox0, &oy0);
    CHECK(bake_char(&g_move_digit, IDX_MOVE_DIGIT, '0') == 0);
    CHECK(bake_char(&g_move_letter, IDX_MOVE_LETTER, 'a') == 0);
    CHECK(rects_overlap(MOVE_DIGIT_X, MOVE_DIGIT_Y, (int)g_move_digit.w,
                        (int)g_move_digit.h, ox0, oy0, (int)g_move_letter.w,
                        (int)g_move_letter.h));

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

    /* Static under-veil region identical at t=0 and t=9; move region differs. */
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
                size_t i = (size_t)y * GLASS_W + (size_t)x;
                if (a[i] != b[i]) {
                    static_same = 0;
                }
            }
        }
        for (y = MOVE_DIGIT_Y; y < MOVE_DIGIT_Y + 28; y++) {
            for (x = MOVE_DIGIT_X; x < MOVE_DIGIT_X + 28; x++) {
                size_t i = (size_t)y * GLASS_W + (size_t)x;
                if (a[i] != b[i]) {
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
    free(g_static_digit.px);
    free(g_static_letter.px);
    free(g_move_digit.px);
    free(g_move_letter.px);
    free(glass);

    if (failures) {
        fprintf(stderr, "test_xy_timed_redraw: %d/%d failed\n", failures,
                checks);
        return 1;
    }
    printf("test_xy_timed_redraw: %d checks ok\n", checks);
    return 0;
}
