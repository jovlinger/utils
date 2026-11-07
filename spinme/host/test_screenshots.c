/*
 * Regen glass screen PNGs under ../screenshots/ (cwd = spinme/host).
 * Screens: main (MPD selected), selecting stub overlay, kv_view, kv_edit.
 */
#include "ta_draw_glass.h"
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
#define GW 3
#define GH 5
#define OUT_DIR "../screenshots"

static ta_pack66_t g_ink[GW * GH];
static ta_pack66_t g_clear[GW * GH];
static ta_shape_bitmap_t g_glyphs[95];
static ta_glyph_map_t g_map;
static ta_pack66_t g_base[PANEL * PANEL];
static ta_pack66_t g_fb[PANEL * PANEL];
static ta_pack66_t g_kv_px[PANEL * PANEL];

static ta_pack66_t *fake_alloc(size_t count) {
    return (ta_pack66_t *)calloc(count, sizeof(ta_pack66_t));
}

static void fake_push(int x, int y, int w, int h, const ta_pack66_t *px,
                      int stride_px) {
    ta_pack66_blit_fb(g_fb, PANEL, PANEL, x, y, w, h, px, stride_px);
}

static const ta_glass_backend_t k_be = {fake_alloc, fake_push, NULL, NULL};

static void build_atlas(void) {
    int i;

    for (i = 0; i < GW * GH; i++) {
        g_ink[i] = ta_pack66_rgba(0x3f, 0x3f, 0x3f, 3);
        g_clear[i] = ta_pack66_rgba(0, 0, 0, 0);
    }
    ta_glyph_map_clear(&g_map);
    for (i = 0; i < 95; i++) {
        char ch = (char)(32 + i);

        memset(&g_glyphs[i], 0, sizeof(g_glyphs[i]));
        g_glyphs[i].tag = TA_SHAPE_TAG_BITMAP;
        g_glyphs[i].w = GW;
        g_glyphs[i].h = GH;
        g_glyphs[i].pixels = ch == ' ' ? g_clear : g_ink;
        CHECK(ta_shape_table_set((unsigned)(1 + i), &g_glyphs[i]) == 0);
        CHECK(ta_glyph_map_set(&g_map, ch, (unsigned)(1 + i)) == 0);
    }
}

static void fb_clear(ta_pack66_t fill) {
    size_t i;

    for (i = 0; i < (size_t)PANEL * (size_t)PANEL; i++) {
        g_fb[i] = fill;
    }
}

static void draw_ring(ta_pack66_t *fb, int cx, int cy, int r_outer, int r_inner,
                      ta_pack66_t ink) {
    int y;
    int x;

    for (y = -r_outer; y <= r_outer; y++) {
        for (x = -r_outer; x <= r_outer; x++) {
            int d2 = x * x + y * y;
            int dx;
            int dy;

            if (d2 > r_outer * r_outer || d2 < r_inner * r_inner) {
                continue;
            }
            dx = cx + x;
            dy = cy + y;
            if (dx < 0 || dy < 0 || dx >= PANEL || dy >= PANEL) {
                continue;
            }
            fb[(size_t)dy * PANEL + (size_t)dx] = ink;
        }
    }
}

static int write_png(const char *name) {
    char path[256];

    snprintf(path, sizeof(path), "%s/%s", OUT_DIR, name);
    return ta_pack66_write_png(path, PANEL, PANEL, g_fb);
}

int main(void) {
    ta_glass_cfg_t cfg;
    ta_kv_editor_t ed;
    ta_pack66_t dark = ta_pack66_rgba(4, 4, 8, 3);
    ta_pack66_t accent = ta_pack66_rgba(50, 40, 8, 3);
    int i;

    (void)mkdir(OUT_DIR, 0755);

    ta_shape_table_reset();
    ta_glass_reset();
    build_atlas();
    for (i = 0; i < PANEL * PANEL; i++) {
        g_base[i] = dark;
    }

    memset(&cfg, 0, sizeof(cfg));
    cfg.panel_w = PANEL;
    cfg.panel_h = PANEL;
    cfg.base_pixels = g_base;
    cfg.glyphs = &g_map;
    cfg.text_h = GH;
    cfg.view_w = 200;
    cfg.hit_pad_x = 8;
    cfg.hit_pad_y = 4;
    cfg.text_x = 48;
    cfg.text_y = 80;
    cfg.gap = 4;
    cfg.button_y = 12;
    ta_glass_set_backend(&k_be);
    ta_glass_set_cfg(&cfg);
    CHECK(ta_glass_install_stack() == 0);

    (void)ta_glass_set_text(TA_DRAW_TEXT_ZONE, "spinme");
    (void)ta_glass_set_text(TA_DRAW_TEXT_ARTIST, "Artist");
    (void)ta_glass_set_text(TA_DRAW_TEXT_ALBUM, "Album");
    (void)ta_glass_set_text(TA_DRAW_TEXT_TITLE, "Main MPD screen");
    ta_glass_set_status(40, 40, 1);

    /* ---- main (MPD selected) ---- */
    fb_clear(dark);
    CHECK(ta_glass_paint() >= 1);
    CHECK(write_png("main_mpd.png") == 0);
    printf("wrote %s/main_mpd.png\n", OUT_DIR);

    /* ---- selecting stub: down arrow + 100x100 circular overlay ---- */
    {
        ta_pack66_t main_copy[PANEL * PANEL];

        ta_glass_set_nav_down(1);
        fb_clear(dark);
        CHECK(ta_glass_paint() >= 1);
        memcpy(main_copy, g_fb, sizeof(main_copy));
        draw_ring(main_copy, PANEL / 2, PANEL / 2, 50, 42, accent);
        memcpy(g_fb, main_copy, sizeof(main_copy));
        CHECK(write_png("selecting_overlay.png") == 0);
        printf("wrote %s/selecting_overlay.png\n", OUT_DIR);
        ta_glass_set_nav_down(0);
    }

    /* ---- KV view as SwapShape page ---- */
    ta_kv_reset();
    CHECK(ta_kv_put("log_receiver_url", "http://gmk.local/logs", 21) ==
          TA_KV_OK);
    CHECK(ta_kv_put("current_controller", "MPD", 3) == TA_KV_OK);
    ta_kv_editor_reset(&ed);
    CHECK(ta_kv_editor_bind(&ed, g_kv_px, PANEL, PANEL) == 0);
    CHECK(ta_kv_editor_refresh(&ed) == 0);
    CHECK(ta_kv_editor_install_shape(&ed) == 0);
    CHECK(ta_glass_add_page(TA_KV_EDITOR_IDX) == 1);
    CHECK(ta_glass_set_page(1) == 0);
    fb_clear(dark);
    CHECK(ta_glass_paint() == 1);
    /* Stamp key/val as bright rows so the PNG is readable without glyphs. */
    {
        size_t n;
        const char *k = ta_kv_editor_key(&ed);
        const char *v = ta_kv_editor_val(&ed);

        for (n = 0; k[n] != '\0' && n < PANEL; n++) {
            g_fb[40 * PANEL + 40 + n] = ta_pack66_rgba(60, 60, 60, 3);
        }
        for (n = 0; v[n] != '\0' && n < PANEL; n++) {
            g_fb[80 * PANEL + 40 + n] = ta_pack66_rgba(40, 55, 40, 3);
        }
        (void)k;
        (void)v;
    }
    CHECK(write_png("kv_view.png") == 0);
    printf("wrote %s/kv_view.png\n", OUT_DIR);

    /* ---- KV edit ---- */
    CHECK(ta_kv_editor_enter(&ed) == 0);
    CHECK(ta_kv_editor_editing(&ed));
    (void)ta_kv_editor_refresh(&ed);
    ed.panel.dirty = 1;
    fb_clear(dark);
    CHECK(ta_glass_paint() == 1);
    draw_ring(g_fb, PANEL / 2, 40, 8, 0, accent); /* caret hint at top */
    CHECK(write_png("kv_edit.png") == 0);
    printf("wrote %s/kv_edit.png\n", OUT_DIR);

    CHECK(ta_glass_set_page(0) == 0);

    if (failures != 0) {
        fprintf(stderr, "test_screenshots: %d/%d checks failed\n", failures,
                checks);
        return 1;
    }
    printf("test_screenshots: %d checks ok\n", checks);
    return 0;
}
