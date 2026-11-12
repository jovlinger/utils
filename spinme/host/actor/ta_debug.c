#include "ta_debug.h"

#include "ta_draw_glass.h"
#include "ta_log_accept.h"
#include "ta_log_rings.h"
#include "ta_uilayout.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int ta_debug_capture_and_log(uint32_t now_ms) {
    char msg[TA_LOG_MSG_MAX];
    const ta_follow_chrome_t *chrome;
    const char *title;
    int n;

    chrome = ta_glass_chrome();
    title = ta_glass_text(TA_DRAW_TEXT_TITLE);
    if (title == NULL) {
        title = "";
    }
    n = snprintf(msg, sizeof(msg), "dbg p=%d d=%d pl=%d pg=%u n=%u t=%.8s",
                 ta_glass_polled(), ta_glass_desired(), ta_glass_playing(),
                 ta_glass_page(),
                 chrome != NULL ? (unsigned)chrome->n : 0u, title);
    if (n < 0) {
        return -1;
    }
    if (ta_log_accept(now_ms, msg) != 0) {
        (void)ta_log_dump(now_ms);
        return -1;
    }
    return ta_log_dump(now_ms);
}

int ta_debug_build_get_debug(uint8_t **out_bytes, size_t *out_len) {
    uint16_t w;
    uint16_t h;
    const ta_pack66_t *px;
    size_t px_n;
    size_t logs_n;
    size_t need;
    size_t o;
    char hdr[96];
    int hn;
    uint8_t *buf;
    ta_log_rings_iter_t it;
    ta_log_rings_entry_t ent;

    if (out_bytes == NULL || out_len == NULL) {
        return -1;
    }
    *out_bytes = NULL;
    *out_len = 0;

    w = 0;
    h = 0;
    px = NULL;
    px_n = 0;
    ta_glass_panel_size(&w, &h);
    if (ta_glass_installed()) {
        px = ta_glass_base_pixels();
        if (px != NULL && w > 0 && h > 0) {
            px_n = (size_t)w * (size_t)h * sizeof(ta_pack66_t);
        }
    }

    logs_n = 0;
    memset(&it, 0, sizeof(it));
    if (ta_log_rings_iter_begin(&it) == 0) {
        while (ta_log_rings_iter_next(&it, &ent) != 0) {
            logs_n++;
        }
        ta_log_rings_iter_end(&it);
    }

    hn = snprintf(hdr, sizeof(hdr), "w=%u&h=%u&fmt=pack66&px_n=%u&logs=%u\n",
                  (unsigned)w, (unsigned)h, (unsigned)px_n, (unsigned)logs_n);
    if (hn < 0) {
        return -1;
    }
    need = (size_t)hn + px_n + 16u + logs_n * 96u;
    buf = (uint8_t *)malloc(need);
    if (buf == NULL) {
        return -1;
    }
    o = 0;
    memcpy(buf + o, hdr, (size_t)hn);
    o += (size_t)hn;
    if (px != NULL && px_n > 0) {
        memcpy(buf + o, px, px_n);
        o += px_n;
    }
    memcpy(buf + o, "\n---logs---\n", 12);
    o += 12;
    memset(&it, 0, sizeof(it));
    if (ta_log_rings_iter_begin(&it) == 0) {
        while (ta_log_rings_iter_next(&it, &ent) != 0) {
            char line[128];
            int ln;

            ln = snprintf(line, sizeof(line), "%llu %s\n",
                          (unsigned long long)ent.time_ms,
                          ent.text != NULL ? ent.text : "");
            if (ln < 0) {
                continue;
            }
            if (o + (size_t)ln > need) {
                break;
            }
            memcpy(buf + o, line, (size_t)ln);
            o += (size_t)ln;
        }
        ta_log_rings_iter_end(&it);
    }
    *out_bytes = buf;
    *out_len = o;
    return 0;
}
