#include "ta_chrome_icons.h"

#include <string.h>

/*
 * Soft white ink. Body a2 is caller-chosen (pending=1, settled=3); fringe
 * is softer when body > 1. Blit/panel must blend a2 into the under-image.
 */
static uint8_t g_body_a2 = TA_CHROME_A2_SETTLED;

static ta_pack66_t ink_a(uint8_t a2) {
    return ta_pack66_rgba(0x3f, 0x3f, 0x3f, (uint8_t)(a2 & 3u));
}

static void put_max(ta_pack66_t *px, uint16_t w, int x, int y, uint8_t a2) {
    size_t i;
    uint8_t r6, g6, b6, cur;

    if (px == NULL || w == 0 || a2 == 0) {
        return;
    }
    if (x < 0 || y < 0 || x >= (int)w || y >= (int)w) {
        return;
    }
    i = (size_t)y * (size_t)w + (size_t)x;
    ta_unpack66(px[i], &r6, &g6, &b6, &cur);
    if (a2 > cur) {
        px[i] = ink_a(a2);
    }
}

static void set_body_a2(uint8_t body_a2) {
    if (body_a2 < 1u) {
        g_body_a2 = 1u;
    } else if (body_a2 > 3u) {
        g_body_a2 = 3u;
    } else {
        g_body_a2 = body_a2;
    }
}

/* Map coverage (0..256) to a2 using g_body_a2 for solid fill. */
static uint8_t a2_cov(int cov256) {
    if (cov256 <= 0) {
        return 0;
    }
    if (cov256 < 128) {
        return g_body_a2 <= 1u ? g_body_a2 : 1u;
    }
    return g_body_a2;
}

/*
 * Coverage for a disk of radius r_q8 (radius in 8.8 fixed) centered at
 * (cx_q8, cy_q8). Pixel centers are at i+0.5 -> (i<<8)+128.
 */
static int disk_cov256(int px, int py, int cx_q8, int cy_q8, int r_q8) {
    int dx = ((px << 8) + 128) - cx_q8;
    int dy = ((py << 8) + 128) - cy_q8;
    /* Approx length via max + min/2 (good enough for AA fringe). */
    int ax = dx < 0 ? -dx : dx;
    int ay = dy < 0 ? -dy : dy;
    int d;
    int outer;
    int inner;
    int t;

    d = ax > ay ? ax + (ay >> 1) : ay + (ax >> 1);
    outer = r_q8 + 128; /* +0.5 px AA band */
    inner = r_q8 - 128;
    if (inner < 0) {
        inner = 0;
    }
    if (d >= outer) {
        return 0;
    }
    if (d <= inner) {
        return 256;
    }
    t = outer - d;
    /* t in (0..256]; scale to 0..256 */
    if (t > 256) {
        t = 256;
    }
    return t;
}

/* Capsule (thick segment) coverage: dist to segment vs half-width. */
static int seg_cov256(int px, int py, int x0, int y0, int x1, int y1,
                      int half_q8) {
    int qx = (px << 8) + 128;
    int qy = (py << 8) + 128;
    int ax = x0 << 8;
    int ay = y0 << 8;
    int bx = x1 << 8;
    int by = y1 << 8;
    int abx = bx - ax;
    int aby = by - ay;
    int apx = qx - ax;
    int apy = qy - ay;
    int64_t ab2;
    int64_t t;
    int cx;
    int cy;
    int dx;
    int dy;
    int axd;
    int ayd;
    int d;
    int outer;
    int inner;
    int cov;

    ab2 = (int64_t)abx * abx + (int64_t)aby * aby;
    if (ab2 <= 0) {
        return disk_cov256(px, py, ax, ay, half_q8);
    }
    /* Multiply then divide (no signed left-shift): t in 0..256. */
    t = ((int64_t)apx * abx + (int64_t)apy * aby) * 256;
    t /= ab2;
    if (t < 0) {
        t = 0;
    }
    if (t > 256) {
        t = 256;
    }
    cx = ax + (int)(((int64_t)abx * t) / 256);
    cy = ay + (int)(((int64_t)aby * t) / 256);
    dx = qx - cx;
    dy = qy - cy;
    axd = dx < 0 ? -dx : dx;
    ayd = dy < 0 ? -dy : dy;
    d = axd > ayd ? axd + (ayd >> 1) : ayd + (axd >> 1);
    outer = half_q8 + 128;
    inner = half_q8 - 128;
    if (inner < 0) {
        inner = 0;
    }
    if (d >= outer) {
        return 0;
    }
    if (d <= inner) {
        return 256;
    }
    cov = outer - d;
    if (cov > 256) {
        cov = 256;
    }
    return cov;
}

static void stroke_seg(ta_pack66_t *px, uint16_t w, int x0, int y0, int x1,
                       int y1, int half_px) {
    int minx;
    int maxx;
    int miny;
    int maxy;
    int x;
    int y;
    int half_q8 = half_px << 8;
    int pad = half_px + 2;

    minx = x0 < x1 ? x0 : x1;
    maxx = x0 > x1 ? x0 : x1;
    miny = y0 < y1 ? y0 : y1;
    maxy = y0 > y1 ? y0 : y1;
    minx -= pad;
    miny -= pad;
    maxx += pad;
    maxy += pad;
    if (minx < 0) {
        minx = 0;
    }
    if (miny < 0) {
        miny = 0;
    }
    if (maxx >= (int)w) {
        maxx = (int)w - 1;
    }
    if (maxy >= (int)w) {
        maxy = (int)w - 1;
    }
    for (y = miny; y <= maxy; y++) {
        for (x = minx; x <= maxx; x++) {
            put_max(px, w, x, y,
                    a2_cov(seg_cov256(x, y, x0, y0, x1, y1, half_q8)));
        }
    }
}

/* Filled triangle with AA fringe (barycentric; edge fade ~1px). */
static void fill_tri_aa(ta_pack66_t *px, uint16_t w, int x0, int y0, int x1,
                        int y1, int x2, int y2) {
    int minx = x0;
    int maxx = x0;
    int miny = y0;
    int maxy = y0;
    int x;
    int y;
    int area;
    int e0x;
    int e0y;
    int e1x;
    int e1y;
    int e2x;
    int e2y;

    if (x1 < minx) {
        minx = x1;
    }
    if (x2 < minx) {
        minx = x2;
    }
    if (x1 > maxx) {
        maxx = x1;
    }
    if (x2 > maxx) {
        maxx = x2;
    }
    if (y1 < miny) {
        miny = y1;
    }
    if (y2 < miny) {
        miny = y2;
    }
    if (y1 > maxy) {
        maxy = y1;
    }
    if (y2 > maxy) {
        maxy = y2;
    }
    minx -= 2;
    miny -= 2;
    maxx += 2;
    maxy += 2;
    if (minx < 0) {
        minx = 0;
    }
    if (miny < 0) {
        miny = 0;
    }
    if (maxx >= (int)w) {
        maxx = (int)w - 1;
    }
    if (maxy >= (int)w) {
        maxy = (int)w - 1;
    }

    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
    if (area == 0) {
        return;
    }
    if (area < 0) {
        /* Swap to CCW. */
        int tx = x1;
        int ty = y1;

        x1 = x2;
        y1 = y2;
        x2 = tx;
        y2 = ty;
        area = -area;
    }
    e0x = x1 - x0;
    e0y = y1 - y0;
    e1x = x2 - x1;
    e1y = y2 - y1;
    e2x = x0 - x2;
    e2y = y0 - y2;

    for (y = miny; y <= maxy; y++) {
        for (x = minx; x <= maxx; x++) {
            /* Pixel center. */
            int cx = (x << 1) + 1; /* 2x fixed */
            int cy = (y << 1) + 1;
            int w0 = e0x * (cy - (y0 << 1)) - e0y * (cx - (x0 << 1));
            int w1 = e1x * (cy - (y1 << 1)) - e1y * (cx - (x1 << 1));
            int w2 = e2x * (cy - (y2 << 1)) - e2y * (cx - (x2 << 1));
            /* Scale edges were in px; cross with 2x coords => area*2. */
            int a2x = area << 1;
            int minw;
            int cov;

            if (w0 < 0 || w1 < 0 || w2 < 0) {
                /* Outside: still may hit AA band via edge distance. */
                int c0 = seg_cov256(x, y, x0, y0, x1, y1, 128);
                int c1 = seg_cov256(x, y, x1, y1, x2, y2, 128);
                int c2 = seg_cov256(x, y, x2, y2, x0, y0, 128);
                int c = c0;

                if (c1 > c) {
                    c = c1;
                }
                if (c2 > c) {
                    c = c2;
                }
                /* Outside edge AA only (thin fringe). */
                if (c > 128) {
                    c = 256 - (c - 128);
                }
                put_max(px, w, x, y, a2_cov(c >> 1));
                continue;
            }
            minw = w0;
            if (w1 < minw) {
                minw = w1;
            }
            if (w2 < minw) {
                minw = w2;
            }
            /* Distance-ish to nearest edge in 2x space; fade last ~2 units. */
            if (minw >= 4) {
                cov = 256;
            } else {
                cov = minw * 64;
                if (cov > 256) {
                    cov = 256;
                }
            }
            (void)a2x;
            put_max(px, w, x, y, a2_cov(cov));
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
        px[i] = TA_PACK66_TRANSPARENT;
    }
}

void ta_chrome_icon_play_outline(ta_pack66_t *px, uint16_t w, uint8_t body_a2) {
    int m = (int)w / 2;
    int left = (int)w / 6;
    int right = (int)w - left - 1;
    int top = (int)w / 6;
    int bot = (int)w - top - 1;
    int half = (int)w / 10;
    uint8_t save = g_body_a2;

    if (half < 3) {
        half = 3;
    }
    set_body_a2(body_a2);
    ta_chrome_icon_clear(px, w);
    stroke_seg(px, w, left, top, left, bot, half);
    stroke_seg(px, w, left, top, right, m, half);
    stroke_seg(px, w, left, bot, right, m, half);
    g_body_a2 = save;
}

void ta_chrome_icon_pause_outline(ta_pack66_t *px, uint16_t w, uint8_t body_a2) {
    int bar_w = (int)w / 7;
    int gap = (int)w / 6;
    int left = (int)w / 2 - gap / 2 - bar_w;
    int right = (int)w / 2 + gap / 2;
    int top = (int)w / 6;
    int bot = (int)w - top - 1;
    int half = bar_w / 2;
    int y;
    uint8_t save = g_body_a2;

    if (half < 2) {
        half = 2;
    }
    set_body_a2(body_a2);
    ta_chrome_icon_clear(px, w);
    for (y = top; y <= bot; y++) {
        put_max(px, w, left, y, g_body_a2);
        put_max(px, w, left + bar_w - 1, y, g_body_a2);
        put_max(px, w, right, y, g_body_a2);
        put_max(px, w, right + bar_w - 1, y, g_body_a2);
    }
    stroke_seg(px, w, left, top, left + bar_w - 1, top, half);
    stroke_seg(px, w, left, bot, left + bar_w - 1, bot, half);
    stroke_seg(px, w, right, top, right + bar_w - 1, top, half);
    stroke_seg(px, w, right, bot, right + bar_w - 1, bot, half);
    stroke_seg(px, w, left, top, left, bot, half);
    stroke_seg(px, w, left + bar_w - 1, top, left + bar_w - 1, bot, half);
    stroke_seg(px, w, right, top, right, bot, half);
    stroke_seg(px, w, right + bar_w - 1, top, right + bar_w - 1, bot, half);
    g_body_a2 = save;
}

void ta_chrome_icon_up_solid(ta_pack66_t *px, uint16_t w) {
    int m = (int)w / 2;
    int top = (int)w / 8;
    int mid = (int)w / 2;
    int bot = (int)w - (int)w / 8;
    int stem_half = (int)w / 9;
    int head_w = (int)w / 2 - 2;
    uint8_t save = g_body_a2;

    if (stem_half < 3) {
        stem_half = 3;
    }
    set_body_a2(TA_CHROME_A2_OPAQUE);
    ta_chrome_icon_clear(px, w);
    fill_tri_aa(px, w, m, top, m - head_w, mid, m + head_w, mid);
    stroke_seg(px, w, m, mid - 2, m, bot, stem_half);
    g_body_a2 = save;
}

void ta_chrome_icon_down_solid(ta_pack66_t *px, uint16_t w) {
    int m = (int)w / 2;
    int top = (int)w / 8;
    int mid = (int)w / 2;
    int bot = (int)w - (int)w / 8;
    int stem_half = (int)w / 9;
    int head_w = (int)w / 2 - 2;
    uint8_t save = g_body_a2;

    if (stem_half < 3) {
        stem_half = 3;
    }
    set_body_a2(TA_CHROME_A2_OPAQUE);
    ta_chrome_icon_clear(px, w);
    fill_tri_aa(px, w, m, bot, m - head_w, mid, m + head_w, mid);
    stroke_seg(px, w, m, top, m, mid + 2, stem_half);
    g_body_a2 = save;
}
