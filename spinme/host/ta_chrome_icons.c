#include "ta_chrome_icons.h"

#include <string.h>

static ta_pack66_t ink(void) {
    return ta_pack66_rgba(0x3f, 0x3f, 0x3f, 3);
}

static void put(ta_pack66_t *px, uint16_t w, int x, int y, ta_pack66_t c) {
    if (x < 0 || y < 0 || x >= (int)w || y >= (int)w) {
        return;
    }
    px[(size_t)y * (size_t)w + (size_t)x] = c;
}

static void plot_line(ta_pack66_t *px, uint16_t w, int x0, int y0, int x1,
                      int y1, ta_pack66_t c) {
    int dx = x1 - x0;
    int dy = y1 - y0;
    int sx = dx < 0 ? -1 : 1;
    int sy = dy < 0 ? -1 : 1;
    int adx = dx < 0 ? -dx : dx;
    int ady = dy < 0 ? -dy : dy;
    int err = adx - ady;
    int x = x0;
    int y = y0;

    for (;;) {
        put(px, w, x, y, c);
        if (x == x1 && y == y1) {
            break;
        }
        {
            int e2 = 2 * err;

            if (e2 > -ady) {
                err -= ady;
                x += sx;
            }
            if (e2 < adx) {
                err += adx;
                y += sy;
            }
        }
    }
}

void ta_chrome_icon_clear(ta_pack66_t *px, uint16_t w) {
    size_t n;
    size_t i;

    if (px == NULL || w == 0) {
        return;
    }
    n = (size_t)w * (size_t)w;
    for (i = 0; i < n; i++) {
        px[i] = ta_pack66_rgba(0, 0, 0, 0);
    }
}

void ta_chrome_icon_play_outline(ta_pack66_t *px, uint16_t w) {
    int m = (int)w / 2;
    int left = (int)w / 5;
    int right = (int)w - left - 1;
    int top = (int)w / 5;
    int bot = (int)w - top - 1;
    ta_pack66_t c = ink();

    ta_chrome_icon_clear(px, w);
    /* Triangle outline pointing right. */
    plot_line(px, w, left, top, left, bot, c);
    plot_line(px, w, left, top, right, m, c);
    plot_line(px, w, left, bot, right, m, c);
}

void ta_chrome_icon_pause_outline(ta_pack66_t *px, uint16_t w) {
    int bar_w = (int)w / 8;
    int gap = (int)w / 6;
    int left = (int)w / 2 - gap / 2 - bar_w;
    int right = (int)w / 2 + gap / 2;
    int top = (int)w / 5;
    int bot = (int)w - top - 1;
    int y;
    int x;
    ta_pack66_t c = ink();

    ta_chrome_icon_clear(px, w);
    for (y = top; y <= bot; y++) {
        for (x = 0; x < bar_w; x++) {
            put(px, w, left + x, y, c);
            put(px, w, right + x, y, c);
        }
        /* Outline: only edges of each bar (hollow look). */
        if (y != top && y != bot) {
            for (x = 1; x < bar_w - 1; x++) {
                put(px, w, left + x, y, ta_pack66_rgba(0, 0, 0, 0));
                put(px, w, right + x, y, ta_pack66_rgba(0, 0, 0, 0));
            }
        }
    }
}

void ta_chrome_icon_up_solid(ta_pack66_t *px, uint16_t w) {
    int m = (int)w / 2;
    int top = (int)w / 6;
    int mid = (int)w / 2;
    int bot = (int)w - (int)w / 6;
    int stem = (int)w / 5;
    int y;
    int x;
    ta_pack66_t c = ink();

    ta_chrome_icon_clear(px, w);
    /* Filled chevron head. */
    for (y = top; y <= mid; y++) {
        int half = ((y - top) * (m - 1)) / (mid - top + 1);

        for (x = m - half; x <= m + half; x++) {
            put(px, w, x, y, c);
        }
    }
    /* Stem. */
    for (y = mid; y <= bot; y++) {
        for (x = m - stem / 2; x <= m + stem / 2; x++) {
            put(px, w, x, y, c);
        }
    }
}

void ta_chrome_icon_down_solid(ta_pack66_t *px, uint16_t w) {
    int m = (int)w / 2;
    int top = (int)w / 6;
    int mid = (int)w / 2;
    int bot = (int)w - (int)w / 6;
    int stem = (int)w / 5;
    int y;
    int x;
    ta_pack66_t c = ink();

    ta_chrome_icon_clear(px, w);
    for (y = mid; y <= bot; y++) {
        int half = ((bot - y) * (m - 1)) / (bot - mid + 1);

        for (x = m - half; x <= m + half; x++) {
            put(px, w, x, y, c);
        }
    }
    for (y = top; y <= mid; y++) {
        for (x = m - stem / 2; x <= m + stem / 2; x++) {
            put(px, w, x, y, c);
        }
    }
}
