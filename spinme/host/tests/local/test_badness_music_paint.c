/* Paint main UI with random album/artist/title from gmk flac tree; print
 * RLC badness. Music root: SPINME_MUSIC_ROOT or /Volumes/flac/files.
 */
#include "ta_draw_glass.h"
#include "ta_glyph_bin.h"
#include "ta_log_accept.h"
#include "ta_pack66_png.h"
#include "ta_kv.h"
#include "ta_runtime_cfg.h"
#include "ta_shape_draw.h"
#include "ta_syslog_host.h"
#include "ta_uilayout.h"

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define PANEL 360
#define FW "../firmware/waveshare-knob-touch-lcd-1.8"
#define GLYPHS_PATH FW "/glyphs.bin"
#define BASE_PATH FW "/disintegration_360.rgba"
#define N_RUNS 12

static ta_pack66_t g_base[PANEL * PANEL];
static ta_pack66_t g_fb[PANEL * PANEL];
static ta_glyph_bin_t g_gb;

static ta_pack66_t *fake_alloc(size_t count) {
    return (ta_pack66_t *)calloc(count, sizeof(ta_pack66_t));
}

static void fake_push(int x, int y, int w, int h, const ta_pack66_t *px,
                      int stride_px) {
    ta_pack66_blit_fb(g_fb, PANEL, PANEL, x, y, w, h, px, stride_px);
}

static const ta_glass_backend_t k_be = {fake_alloc, fake_push, NULL, NULL};

static int split_album_dir(const char *name, char *artist, size_t artist_cap,
                           char *album, size_t album_cap) {
    const char *sep = strstr(name, " - ");
    size_t alen;

    if (sep == NULL) {
        snprintf(artist, artist_cap, "%s", name);
        snprintf(album, album_cap, "%s", name);
        return 0;
    }
    alen = (size_t)(sep - name);
    if (alen >= artist_cap) {
        alen = artist_cap - 1;
    }
    memcpy(artist, name, alen);
    artist[alen] = '\0';
    snprintf(album, album_cap, "%s", sep + 3);
    return 0;
}

static int load_album_names(char ***out_names, size_t *out_n, const char *root) {
    DIR *d;
    struct dirent *ent;
    char **names = NULL;
    size_t n = 0;
    size_t cap = 0;

    d = opendir(root);
    if (d == NULL) {
        return -1;
    }
    while ((ent = readdir(d)) != NULL) {
        char path[1024];
        if (ent->d_name[0] == '.' || ent->d_name[0] == '_') {
            continue;
        }
        snprintf(path, sizeof(path), "%s/%s", root, ent->d_name);
        {
            DIR *sub = opendir(path);
            if (sub == NULL) {
                continue;
            }
            closedir(sub);
        }
        if (n + 1 > cap) {
            size_t ncap = cap ? cap * 2u : 64u;
            char **nn = (char **)realloc(names, ncap * sizeof(char *));
            if (nn == NULL) {
                closedir(d);
                return -1;
            }
            names = nn;
            cap = ncap;
        }
        names[n] = strdup(ent->d_name);
        if (names[n] == NULL) {
            closedir(d);
            return -1;
        }
        n++;
    }
    closedir(d);
    *out_names = names;
    *out_n = n;
    return 0;
}

int main(void) {
    const char *root;
    char **albums = NULL;
    size_t n_albums = 0;
    ta_glass_cfg_t cfg;
    int run;
    char report[512];

    root = getenv("SPINME_MUSIC_ROOT");
    if (root == NULL || root[0] == '\0') {
        root = "/Volumes/flac/files";
    }
    if (load_album_names(&albums, &n_albums, root) != 0 || n_albums == 0) {
        fprintf(stderr, "test_badness_music_paint: no albums under %s\n", root);
        return 1;
    }
    srand((unsigned)time(NULL));

    ta_shape_table_reset();
    ta_glass_reset();
    ta_sd_reset();
    if (ta_glyph_bin_load(&g_gb, GLYPHS_PATH) != 0) {
        fprintf(stderr, "glyphs load failed\n");
        return 1;
    }
    if (ta_base_from_rgba_file(g_base, PANEL, PANEL, BASE_PATH) != 0) {
        fprintf(stderr, "base rgba load failed\n");
        return 1;
    }

    memset(&cfg, 0, sizeof(cfg));
    cfg.panel_w = PANEL;
    cfg.panel_h = PANEL;
    cfg.base_pixels = g_base;
    cfg.glyphs = &g_gb.map;
    cfg.kern_table = g_gb.kern;
    cfg.text_h = g_gb.text_h;
    cfg.view_w = 312;
    cfg.hit_pad_x = 12;
    cfg.hit_pad_y = 6;
    cfg.text_x = 24;
    cfg.text_y = 96;
    cfg.gap = 4;
    cfg.button_y = 8;
    ta_glass_set_backend(&k_be);
    ta_glass_set_cfg(&cfg);
    if (ta_glass_install_stack() != 0) {
        fprintf(stderr, "install_stack failed\n");
        return 1;
    }

    printf("music_root=%s albums=%zu runs=%d\n", root, n_albums, N_RUNS);
    for (run = 0; run < N_RUNS; run++) {
        size_t pick = (size_t)rand() % n_albums;
        char artist[128];
        char album[128];
        char title[160];

        split_album_dir(albums[pick], artist, sizeof(artist), album,
                        sizeof(album));
        snprintf(title, sizeof(title), "Track %d", (rand() % 18) + 1);
        (void)ta_glass_set_text(TA_DRAW_TEXT_ZONE, "spinme");
        (void)ta_glass_set_text(TA_DRAW_TEXT_ARTIST, artist);
        (void)ta_glass_set_text(TA_DRAW_TEXT_ALBUM, album);
        (void)ta_glass_set_text(TA_DRAW_TEXT_TITLE, title);
        ta_glass_set_status((uint8_t)(rand() % 100), (uint8_t)(rand() % 100), 1,
                            1);
        memcpy(g_fb, g_base, sizeof(g_fb));
        if (ta_glass_paint() < 1) {
            fprintf(stderr, "paint failed run %d\n", run);
            return 1;
        }
        printf("run %02d artist=%s album=%s title=%s\n", run, artist, album,
               title);
    }

    if (ta_sd_format_badness_report(report, sizeof(report)) == 0) {
        printf("badness: (none sampled -- XY scratch may be retargeted)\n");
    } else {
        printf("badness_report:\n%s", report);
        ta_kv_install_factory();
        ta_log_accept_reset();
        ta_syslog_install_default_sender();
        ta_log_apply_kv_settings();
        ta_log_accept(1, report);
        if (ta_log_dump(2) != 0) {
            fprintf(stderr, "QuLog dump failed (udp://qnap.local:514)\n");
            return 1;
        }
        printf("badness logged to QuLog udp://qnap.local:514\n");
    }

    ta_glyph_bin_fini(&g_gb);
    {
        size_t i;
        for (i = 0; i < n_albums; i++) {
            free(albums[i]);
        }
        free(albums);
    }
    printf("test_badness_music_paint: ok\n");
    return 0;
}
