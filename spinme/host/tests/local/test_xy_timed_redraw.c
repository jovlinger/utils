/*
 * local/: timed XY redraw via XYShape-only glass path.
 * - Clock face: wall UTC now as HH:MM:SSZ (time()/gmtime); 1s sleep between
 *   frames so the face changes across t=0..9.
 * - Alpha (timed): spelled words zero..nine, offset to overlap the clock.
 * - Veil z=3: 0x08080801 as R,G,B,A -> pack66.
 * Glass: only ta_sd_xy_blit_glass (RLC spans + ta_sd_blend). No direct blits.
 * PNGs under build/xy_timed/; REGEN_XY_TIMED copies to screenshots/xy_timed/
 * (live clock => not bit-identical across runs; compare is opt-in via REGEN).
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
#include <time.h>
#include <unistd.h>

enum {
    GLASS_W = 280,
    GLASS_H = 80,
    TIMES = 10,
    CLOCK_X = 8,
    CLOCK_Y = 18,
    ALPHA_DX = 10,
    ALPHA_DY = 8,
    VEIL_X = 0,
    VEIL_Y = 0,
    VEIL_W = 260,
    VEIL_H = 60,
    PNG_SCALE = 4,
    IDX_BM_CLOCK = 202,
    IDX_BM_ALPHA = 203,
    IDX_BM_VEIL = 204,
    IDX_XY_CLOCK = 212,
    IDX_XY_VEIL = 213,
    IDX_XY_ALPHA = 214,
    BAKE_GLYPH_CAP = 16
};

#define FW "../firmware/waveshare-knob-touch-lcd-1.8"
#define GLYPHS_PATH FW "/glyphs.bin"
#define GOLDEN_DIR "../screenshots/xy_timed"
#define ACTUAL_DIR "build/xy_timed"
#define VEIL_PX ta_pack66_rgba(0x08, 0x08, 0x08, 1)

static const char *const k_words[TIMES] = {
    "zero", "one",  "two",   "three", "four",
    "five", "six",  "seven", "eight", "nine",
};

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

/* UTC wall clock -> "HH:MM:SSZ" (datetime.utcnow / time.now UTC). */
static void format_clock_now(char out[16]) {
    time_t now = time(NULL);
    struct tm tm_utc;

    if (now == (time_t)-1 || gmtime_r(&now, &tm_utc) == NULL) {
        snprintf(out, 16, "??:??:??Z");
        return;
    }
    snprintf(out, 16, "%02d:%02d:%02dZ", tm_utc.tm_hour, tm_utc.tm_min,
             tm_utc.tm_sec);
}

static void glass_clear(ta_pack66_t *g) {
    memset(g, 0, (size_t)GLASS_W * (size_t)GLASS_H * sizeof(*g));
}

static int bake_ascii_into_sd(unsigned bm_idx, const char *ascii,
                              uint16_t *out_w, uint16_t *out_h) {
    ta_shape_l2r_t line;
    uint32_t pack[BAKE_GLYPH_CAP];
    int8_t kern[BAKE_GLYPH_CAP];
    ta_uilayout_t uilo;
    ta_draw_scene_t scene;
    ta_phase1_opts_t opts;
    ta_shape_bitmap_t *hdr;
    ta_sd_shape_t *bm;

    if (ascii == NULL || ascii[0] == '\0') {
        return -1;
    }
    memset(&line, 0, sizeof(line));
    if (ta_text_build(&line, ascii, &g_gb.map, g_gb.kern, pack, BAKE_GLYPH_CAP,
                      kern, BAKE_GLYPH_CAP) != 0) {
        return -1;
    }
    line.pixels = (ta_pack66_t *)calloc((size_t)line.w * (size_t)line.h,
                                        sizeof(ta_pack66_t));
    if (line.pixels == NULL) {
        return -1;
    }
    line.flags = ta_shape_flags_set_dirty(line.flags, 1);
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
    /* Carry L2R summed glyph Ns onto the sd bitmap. */
    bm->flags = ta_shape_flags_set_rlc_n(bm->flags,
                                         ta_shape_flags_rlc_n(line.flags));
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
    ta_sd_shape_t *ch = ta_sd_get(child_idx);
    unsigned rn = 1u;

    if (ch != NULL) {
        rn = ta_shape_flags_rlc_n(ch->flags);
        if (rn == 0) {
            rn = 1u;
        }
    }
    if (ta_sd_alloc_bitmap_rlc(xy_idx, TA_SD_TAG_XY, w, h, (uint8_t)rn) != 0) {
        return -1;
    }
    xy = ta_sd_get(xy_idx);
    xy->u.xy.child = (uint16_t)child_idx;
    xy->u.xy.x = x;
    xy->u.xy.y = y;
    if (ta_sd_xy_rebuild_from_child(xy_idx) != 0) {
        return -1;
    }
    ta_sd_xy_derive_rlc(xy, NULL, xy->pixels);
    return 0;
}

static void alpha_xy(int t, int *x, int *y) {
    (void)t;
    *x = CLOCK_X + ALPHA_DX;
    *y = CLOCK_Y + ALPHA_DY;
}

static int refresh_xy(unsigned xy_idx, unsigned bm_idx, int16_t x, int16_t y) {
    ta_sd_shape_t *ch = ta_sd_get(bm_idx);

    if (ch == NULL) {
        return -1;
    }
    return make_xy(xy_idx, bm_idx, x, y, ch->w, ch->h);
}

static void xy_reset_badness(unsigned xy_idx) {
    ta_sd_shape_t *xy = ta_sd_get(xy_idx);

    if (xy == NULL) {
        return;
    }
    xy->badness_overflow_avg = 0.f;
    xy->badness_slack_avg = 0.f;
    xy->badness_paints = 0;
}

static void xy_mark_content_dirty(unsigned xy_idx) {
    ta_sd_shape_t *xy = ta_sd_get(xy_idx);

    if (xy == NULL || xy->pixels == NULL) {
        return;
    }
    ta_sd_xy_derive_rlc(xy, NULL, xy->pixels);
}

static void xy_redraw(ta_pack66_t *glass, int t, char clock_out[16]) {
    int ox;
    int oy;
    const char *word = k_words[t];
    uint16_t dw = 0;
    uint16_t dh = 0;
    const unsigned order[] = {IDX_XY_CLOCK, IDX_XY_VEIL, IDX_XY_ALPHA};
    size_t i;
    char report[512];

    glass_clear(glass);
    format_clock_now(clock_out);

    CHECK(bake_ascii_into_sd(IDX_BM_CLOCK, clock_out, &dw, &dh) == 0);
    CHECK(bake_ascii_into_sd(IDX_BM_ALPHA, word, &dw, &dh) == 0);
    alpha_xy(t, &ox, &oy);

    CHECK(refresh_xy(IDX_XY_CLOCK, IDX_BM_CLOCK, (int16_t)CLOCK_X,
                     (int16_t)CLOCK_Y) == 0);
    CHECK(refresh_xy(IDX_XY_ALPHA, IDX_BM_ALPHA, (int16_t)ox, (int16_t)oy) ==
          0);
    xy_mark_content_dirty(IDX_XY_VEIL);

    for (i = 0; i < sizeof(order) / sizeof(order[0]); i++) {
        xy_reset_badness(order[i]);
    }
    ta_sd_glass_paint_xys(glass, GLASS_W, GLASS_H, order,
                          sizeof(order) / sizeof(order[0]));

    printf("t=%d clock=%s alpha=%s  (idx: 212=clock 213=veil 214=alpha)\n", t,
           clock_out, word);
    if (ta_sd_format_badness_report(report, sizeof(report)) > 0) {
        printf("%s", report);
    } else {
        printf("(none)\n");
    }
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
    char clock0[16];

    glass = (ta_pack66_t *)calloc((size_t)GLASS_W * (size_t)GLASS_H,
                                  sizeof(*glass));
    CHECK(glass != NULL);
    CHECK(VEIL_PX == 0x01080808u);

    ta_shape_table_reset();
    ta_sd_reset();
    ta_glyph_bin_reset(&g_gb);
    CHECK(ta_glyph_bin_load(&g_gb, GLYPHS_PATH) == 0);

    format_clock_now(clock0);
    CHECK(bake_ascii_into_sd(IDX_BM_CLOCK, clock0, &sw, &sh) == 0);
    CHECK(make_xy(IDX_XY_CLOCK, IDX_BM_CLOCK, (int16_t)CLOCK_X, (int16_t)CLOCK_Y,
                  sw, sh) == 0);
    alpha_xy(0, &ox0, &oy0);
    CHECK(bake_ascii_into_sd(IDX_BM_ALPHA, k_words[0], &sw, &sh) == 0);
    CHECK(make_xy(IDX_XY_ALPHA, IDX_BM_ALPHA, (int16_t)ox0, (int16_t)oy0, sw,
                  sh) == 0);
    CHECK(rects_overlap(CLOCK_X, CLOCK_Y, (int)ta_sd_get(IDX_BM_CLOCK)->w,
                        (int)ta_sd_get(IDX_BM_CLOCK)->h, ox0, oy0,
                        (int)ta_sd_get(IDX_BM_ALPHA)->w,
                        (int)ta_sd_get(IDX_BM_ALPHA)->h));

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

    printf("wall_utc_sample=%s\n", clock0);

    for (t = 0; t < TIMES; t++) {
        int ox;
        int oy;
        char actual[160];
        char golden[160];
        char clock[16];
        const int regen = (getenv("REGEN_XY_TIMED") != NULL);

        if (t > 0) {
            sleep(1);
        }
        xy_redraw(glass, t, clock);
        alpha_xy(t, &ox, &oy);

        CHECK(count_nonzero(glass, CLOCK_X, CLOCK_Y, 72, (int)g_gb.text_h) > 0);
        CHECK(count_nonzero(glass, ox, oy, 40, (int)g_gb.text_h) > 0);
        CHECK(glass[(size_t)(GLASS_H - 1) * GLASS_W + (GLASS_W - 1)] == 0);

        snprintf(actual, sizeof(actual), ACTUAL_DIR "/t%02d.png", t);
        snprintf(golden, sizeof(golden), GOLDEN_DIR "/t%02d.png", t);
        CHECK(ta_pack66_write_png_scaled(actual, GLASS_W, GLASS_H, glass,
                                         PNG_SCALE) == 0);
        if (regen) {
            CHECK(copy_file(actual, golden) == 0);
            printf("regen %s\n", golden);
        }
    }

    {
        ta_pack66_t *a =
            (ta_pack66_t *)calloc((size_t)GLASS_W * GLASS_H, sizeof(*a));
        ta_pack66_t *b =
            (ta_pack66_t *)calloc((size_t)GLASS_W * GLASS_H, sizeof(*b));
        int x;
        int y;
        int alpha_diff = 0;
        int clock_diff = 0;
        char ca[16];
        char cb[16];

        CHECK(a != NULL && b != NULL);
        xy_redraw(a, 0, ca);
        sleep(1);
        xy_redraw(b, 9, cb);
        CHECK(strcmp(ca, cb) != 0);
        clock_diff = strcmp(ca, cb) != 0;
        CHECK(clock_diff == 1);
        for (y = CLOCK_Y + ALPHA_DY; y < CLOCK_Y + ALPHA_DY + 28; y++) {
            for (x = CLOCK_X + ALPHA_DX; x < CLOCK_X + ALPHA_DX + 80; x++) {
                size_t ii = (size_t)y * GLASS_W + (size_t)x;
                if (a[ii] != b[ii]) {
                    alpha_diff = 1;
                }
            }
        }
        CHECK(alpha_diff == 1);
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
