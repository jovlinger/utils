/* local/: pixel-perfect glass UI vs PNG goldens in ../../screenshots/
 * (paths assume cwd spinme/host). Compares RGB via ta_pack66_png_pixel_equal.
 * Refresh: SPINME_UI_UPDATE_GOLDEN=1 ./build/test_screenshots
 */
#include "ta_draw_glass.h"
#include "ta_draw_phase1.h"
#include "ta_glyph_bin.h"
#include "ta_kv.h"
#include "ta_kv_editor.h"
#include "ta_pack66_png.h"
#include "ta_text.h"
#include "ta_uilayout.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

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

#define PANEL 360
#define GOLDEN_DIR "../screenshots"
#define ACTUAL_DIR "build/ui_actual"
#define PNG_SCALE 3
#define FW "../firmware/waveshare-knob-touch-lcd-1.8"
/* GOLDEN/FW paths are relative to make cwd (spinme/host), not this file. */
#define GLYPHS_PATH FW "/glyphs.bin"
#define BASE_PATH FW "/disintegration_360.rgba"

/* Match ta_glass_device.cpp placements. */
static const int kTextX = 24;
static const int kTextY = 96;
static const int kGap = 4;
static const int kButtonY = 8;
static const uint16_t kViewW = 312;
static const uint16_t kHitPadX = 12;
static const uint16_t kHitPadY = 6;

static ta_pack66_t g_base[PANEL * PANEL];
static ta_pack66_t g_fb[PANEL * PANEL];
static ta_pack66_t g_kv_px[PANEL * PANEL];
static ta_glyph_bin_t g_gb;

static ta_pack66_t *fake_alloc(size_t count) {
    return (ta_pack66_t *)calloc(count, sizeof(ta_pack66_t));
}

static void fake_push(int x, int y, int w, int h, const ta_pack66_t *px,
                      int stride_px) {
    ta_pack66_blit_fb(g_fb, PANEL, PANEL, x, y, w, h, px, stride_px);
}

static const ta_glass_backend_t k_be = {fake_alloc, fake_push, NULL, NULL};

static void fb_clear_from_base(void) {
    memcpy(g_fb, g_base, sizeof(g_fb));
}

static int copy_file(const char *src, const char *dst) {
    FILE *in;
    FILE *out;
    char buf[4096];
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

/* Write actual PNG; compare to golden (or refresh golden if env set). */
static int check_png(const char *name) {
    char actual[512];
    char golden[512];
    int eq;
    const char *upd = getenv("SPINME_UI_UPDATE_GOLDEN");

    snprintf(actual, sizeof(actual), "%s/%s", ACTUAL_DIR, name);
    snprintf(golden, sizeof(golden), "%s/%s", GOLDEN_DIR, name);
    if (ta_pack66_write_png_scaled(actual, PANEL, PANEL, g_fb, PNG_SCALE) !=
        0) {
        fprintf(stderr, "write failed: %s\n", actual);
        return -1;
    }
    if (upd != NULL && upd[0] != '\0' && upd[0] != '0') {
        if (copy_file(actual, golden) != 0) {
            fprintf(stderr, "golden update failed: %s\n", golden);
            return -1;
        }
        printf("updated golden %s\n", golden);
        return 0;
    }
    eq = ta_pack66_png_pixel_equal(actual, golden);
    if (eq < 0) {
        fprintf(stderr, "png compare IO error: %s vs %s\n", actual, golden);
        return -1;
    }
    if (eq != 0) {
        fprintf(stderr, "PIXEL DIFF: %s != golden %s\n", actual, golden);
        return -1;
    }
    printf("ok %s\n", name);
    return 0;
}

int main(void) {
    ta_glass_cfg_t cfg;
    ta_kv_editor_t ed;

    (void)mkdir("build", 0755);
    (void)mkdir(ACTUAL_DIR, 0755);
    (void)mkdir(GOLDEN_DIR, 0755);

    ta_shape_table_reset();
    ta_glass_reset();
    CHECK(ta_glyph_bin_load(&g_gb, GLYPHS_PATH) == 0);
    CHECK(g_gb.text_h >= 20);
    CHECK(ta_base_from_rgba_file(g_base, PANEL, PANEL, BASE_PATH) == 0);

    memset(&cfg, 0, sizeof(cfg));
    cfg.panel_w = PANEL;
    cfg.panel_h = PANEL;
    cfg.base_pixels = g_base;
    cfg.glyphs = &g_gb.map;
    cfg.kern_table = g_gb.kern;
    cfg.text_h = g_gb.text_h;
    cfg.view_w = kViewW;
    cfg.hit_pad_x = kHitPadX;
    cfg.hit_pad_y = kHitPadY;
    cfg.text_x = kTextX;
    cfg.text_y = kTextY;
    cfg.gap = kGap;
    cfg.button_y = kButtonY;
    ta_glass_set_backend(&k_be);
    ta_glass_set_cfg(&cfg);
    CHECK(ta_glass_install_stack() == 0);

    /* Defaults like a quiet boot: zone + clock already set; status unknown. */
    (void)ta_glass_set_text(TA_DRAW_TEXT_ZONE, "spinme");
    (void)ta_glass_set_text(TA_DRAW_TEXT_ARTIST, "");
    (void)ta_glass_set_text(TA_DRAW_TEXT_ALBUM, "");
    (void)ta_glass_set_text(TA_DRAW_TEXT_TITLE, "");
    ta_glass_set_status(TA_GLASS_UNKNOWN, TA_GLASS_UNKNOWN, 0, 0);

    fb_clear_from_base();
    CHECK(ta_glass_paint() >= 1);
    CHECK(check_png("main_mpd.png") == 0);

    /* With sample track text (still the main screen). */
    (void)ta_glass_set_text(TA_DRAW_TEXT_ARTIST, "Artist Name");
    (void)ta_glass_set_text(TA_DRAW_TEXT_ALBUM, "Album Title");
    (void)ta_glass_set_text(TA_DRAW_TEXT_TITLE, "Track Title Goes Here");
    ta_glass_set_status(42, 42, 1, 1);
    fb_clear_from_base();
    CHECK(ta_glass_paint() >= 1);
    CHECK(check_png("main_playing.png") == 0);

    ta_kv_reset();
    CHECK(ta_kv_put("log_receiver_url", "http://gmk.local/logs", 21) ==
          TA_KV_OK);
    CHECK(ta_kv_put("current_controller", "MPD", 3) == TA_KV_OK);
    ta_kv_editor_reset(&ed);
    CHECK(ta_kv_editor_bind(&ed, g_kv_px, PANEL, PANEL) == 0);
    CHECK(ta_kv_editor_refresh(&ed) == 0);
    CHECK(ta_kv_editor_install_shape(&ed) == 0);
    CHECK(ta_glass_add_page(TA_KV_EDITOR_IDX) == 1);

    {
        const ta_follow_chrome_t *chrome = ta_glass_chrome();
        uint16_t nx =
            (uint16_t)(ta_uilo_x(chrome->uilo[TA_FOLLOW_NAV]) + 8);
        uint16_t ny =
            (uint16_t)(ta_uilo_y(chrome->uilo[TA_FOLLOW_NAV]) + 8);

        CHECK(ta_glass_touch(nx, ny, 1) == 0);
        CHECK(ta_glass_selecting());
        fb_clear_from_base();
        CHECK(ta_glass_paint() >= 1);
        CHECK(check_png("selecting_overlay.png") == 0);
        CHECK(ta_glass_touch(nx, ny, 1) == 0);
        CHECK(!ta_glass_selecting());
    }

    CHECK(ta_glass_set_page(1) == 0);
    fb_clear_from_base();
    CHECK(ta_glass_paint() == 1);
    /* Overlay real glyph lines on the KV page still (editor paint is stub). */
    {
        static const char *lines[2] = {"current_controller = MPD",
                                      "log_receiver_url = http://gmk.local/logs"};
        int li;

        for (li = 0; li < 2; li++) {
            ta_shape_l2r_t line;
            uint32_t pack[48];
            int8_t kern[64];
            ta_pack66_t *line_px;
            ta_draw_scene_t scene;
            ta_uilayout_t uilo;
            ta_phase1_opts_t opts;
            int y = kTextY + li * ((int)g_gb.text_h + kGap);

            memset(&line, 0, sizeof(line));
            CHECK(ta_text_build(&line, lines[li], &g_gb.map, g_gb.kern, pack, 48,
                                kern, 64) == 0);
            CHECK(ta_shape_l2r_compute_size(&line) == 0);
            /* phase1 may recompute size; keep a full-line budget. */
            line_px = fake_alloc((size_t)PANEL * (size_t)g_gb.text_h * 2u);
            CHECK(line_px != NULL);
            line.pixels = line_px;
            line.dirty = 1;
            CHECK(ta_shape_table_set((unsigned)(930 + li),
                                     (ta_shape_bitmap_t *)(void *)&line) == 0);
            uilo = ta_uilo_make(1, kTextX, y, (unsigned)(930 + li));
            memset(&scene, 0, sizeof(scene));
            scene.uilo = &uilo;
            scene.n_uilo = 1;
            memset(&opts, 0, sizeof(opts));
            opts.base_shape_idx = TA_GLASS_IDX_BASE;
            CHECK(ta_draw_phase1(&scene, &opts) == 0);
            ta_pack66_blit_fb(g_fb, PANEL, PANEL, kTextX, y, (int)line.w,
                              (int)line.h, line.pixels, (int)line.w);
            free(line_px);
        }
    }
    CHECK(check_png("kv_view.png") == 0);

    CHECK(ta_kv_editor_enter(&ed) == 0);
    fb_clear_from_base();
    CHECK(ta_glass_paint() == 1);
    CHECK(check_png("kv_edit.png") == 0);

    CHECK(ta_glass_set_page(0) == 0);
    ta_glyph_bin_fini(&g_gb);

    if (failures != 0) {
        fprintf(stderr, "test_screenshots: %d/%d checks failed\n", failures,
                checks);
        return 1;
    }
    printf("test_screenshots: %d checks ok\n", checks);
    return 0;
}
