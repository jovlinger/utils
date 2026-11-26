/* Host: 6 oclock debug chrome placement + capture -> Log dump. */
#include "ta_debug.h"
#include "ta_draw_glass.h"
#include "ta_follow_chrome.h"
#include "ta_hit_dispatch.h"
#include "ta_log_accept.h"
#include "ta_text.h"

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

static int g_sends;

static int send_log(const char *url, const ta_log_accept_event_t *rows,
                    size_t n, void *ud) {
    (void)url;
    (void)ud;
    g_sends++;
    CHECK(n >= 1);
    CHECK(rows != NULL);
    CHECK(strncmp(rows[0].message, "dbg ", 4) == 0);
    return 0;
}

static ta_pack66_t *alloc_px(size_t count) {
    static ta_pack66_t pool[360 * 360];
    static size_t used;
    ta_pack66_t *p;

    if (used + count > sizeof(pool) / sizeof(pool[0])) {
        return NULL;
    }
    p = pool + used;
    used += count;
    return p;
}

static void push_rect(int x, int y, int w, int h, const ta_pack66_t *px,
                      int stride_px) {
    (void)x;
    (void)y;
    (void)w;
    (void)h;
    (void)px;
    (void)stride_px;
}

int main(void) {
    ta_follow_chrome_t chrome;
    unsigned shapes[TA_FOLLOW_N] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10};
    ta_follow_metrics_t m;
    uint16_t sw[TA_FOLLOW_N];
    uint16_t sh[TA_FOLLOW_N];
    size_t i;
    ta_glass_backend_t be;
    ta_glass_cfg_t cfg;
    ta_glyph_map_t glyphs;

    CHECK(ta_follow_chrome_build(&chrome, shapes) == 0);
    CHECK(chrome.accept_hit[TA_FOLLOW_DEBUG] == 1);
    CHECK(chrome.fn_enum[TA_FOLLOW_DEBUG] == (uint8_t)TA_FN_DEBUG);
    memset(&m, 0, sizeof(m));
    m.panel_w = 360;
    m.panel_h = 360;
    m.text_x = 20;
    m.text_y = 40;
    m.text_h = 20;
    m.gap = 4;
    m.button_y = 12;
    m.transport_w = 90;
    m.transport_h = 90;
    m.nav_w = 60;
    m.nav_h = 60;
    m.debug_w = 60;
    m.debug_h = 60;
    CHECK(ta_follow_chrome_place(&chrome, &m) == 0);
    CHECK(ta_uilo_y(chrome.uilo[TA_FOLLOW_DEBUG]) >
          ta_uilo_y(chrome.uilo[TA_FOLLOW_TRANSPORT]));
    CHECK(ta_uilo_y(chrome.uilo[TA_FOLLOW_DEBUG]) >= 360 - 60 - 8);

    for (i = 0; i < TA_FOLLOW_N; i++) {
        sw[i] = 60;
        sh[i] = 60;
    }
    {
        int dx = ta_uilo_x(chrome.uilo[TA_FOLLOW_DEBUG]) + 1;
        int dy = ta_uilo_y(chrome.uilo[TA_FOLLOW_DEBUG]) + 1;
        CHECK(ta_hit_walk(&chrome, dx, dy, sw, sh) == TA_HIT_DEBUG);
    }

    memset(&glyphs, 0, sizeof(glyphs));
    memset(&be, 0, sizeof(be));
    be.alloc_px = alloc_px;
    be.push_rect = push_rect;
    memset(&cfg, 0, sizeof(cfg));
    cfg.panel_w = 360;
    cfg.panel_h = 360;
    cfg.text_x = 20;
    cfg.text_y = 40;
    cfg.text_h = 16;
    cfg.gap = 4;
    cfg.button_y = 12;
    cfg.glyphs = &glyphs;

    ta_glass_reset();
    ta_glass_set_backend(&be);
    ta_glass_set_cfg(&cfg);
    /* Glyphs incomplete: install may fail; capture still works if not installed. */
    ta_log_accept_reset();
    ta_log_set_url("syslog://test");
    ta_log_set_sender(send_log, NULL);
    g_sends = 0;
    CHECK(ta_debug_capture_and_log(123) == 0);
    CHECK(g_sends == 1);
    CHECK(ta_log_accept_count() == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_debug: %d checks ok\n", checks);
    return 0;
}
