#include "ta_artwork.h"

#include "ta_draw_events.h"
#include "ta_net_events.h"
#include "ta_sched_events.h"

#include <stdlib.h>
#include <string.h>

void ta_artwork_calm_rgba(uint8_t *rgba, size_t w, size_t h) {
    size_t n;
    size_t i;
    uint8_t *tmp;

    if (rgba == NULL || w == 0 || h == 0) {
        return;
    }
    n = w * h;
    tmp = (uint8_t *)malloc(n * 4u);
    if (tmp == NULL) {
        return;
    }
    memcpy(tmp, rgba, n * 4u);
    for (i = 0; i < n; i++) {
        size_t x = i % w;
        size_t y = i / w;
        int sum_r = 0, sum_g = 0, sum_b = 0, cnt = 0;
        int dy, dx;

        for (dy = -1; dy <= 1; dy++) {
            for (dx = -1; dx <= 1; dx++) {
                int xx = (int)x + dx;
                int yy = (int)y + dy;
                size_t j;
                if (xx < 0 || yy < 0 || xx >= (int)w || yy >= (int)h) {
                    continue;
                }
                j = (size_t)yy * w + (size_t)xx;
                sum_r += tmp[j * 4];
                sum_g += tmp[j * 4 + 1];
                sum_b += tmp[j * 4 + 2];
                cnt++;
            }
        }
        if (cnt > 0) {
            int r = sum_r / cnt;
            int g = sum_g / cnt;
            int b = sum_b / cnt;
            int gray = (r + g + b) / 3;
            /* Light desat toward gray. */
            rgba[i * 4] = (uint8_t)((r * 3 + gray) / 4);
            rgba[i * 4 + 1] = (uint8_t)((g * 3 + gray) / 4);
            rgba[i * 4 + 2] = (uint8_t)((b * 3 + gray) / 4);
        }
    }
    free(tmp);
}

int ta_artwork_is_default(uint32_t fingerprint) {
    return fingerprint == TA_ART_DEFAULT_FP;
}

int ta_artwork_on_album_change(const char *net_dst, const char *draw_dst,
                               ta_session_id_t session, uint32_t time_remain_ms) {
    if (net_dst == NULL || draw_dst == NULL) {
        return -1;
    }
    /* Immediate proactive poll shortly after change. */
    if (ta_sched_arm_oneshot(net_dst, session, 50, TA_EV_NET_POLL) != 0) {
        return -1;
    }
    /* Time-remaining one-shot toward Draw update (clock/chrome). */
    if (time_remain_ms == 0) {
        time_remain_ms = 1000;
    }
    if (ta_sched_arm_oneshot(draw_dst, session, time_remain_ms,
                             TA_EV_DRAW_UPDATE) != 0) {
        return -1;
    }
    return 0;
}
