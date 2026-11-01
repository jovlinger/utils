#include "ta_artwork.h"

#include "ta_draw_events.h"
#include "ta_net_events.h"
#include "ta_sched_events.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

/* Quadratic B-spline weight for |d| in Q8 (256 == 1 px). */
static int qbspline_w_q8(int d_q8) {
    int a = d_q8 < 0 ? -d_q8 : d_q8;
    if (a >= 384) {
        return 0;
    }
    if (a < 128) {
        /* 0.75 - u^2 */
        return 192 - (a * a) / TA_ART_Q8_ONE;
    }
    /* 0.5 * (1.5 - u)^2 */
    {
        int t = 384 - a;
        return (t * t) / 512;
    }
}

static int clampi(int v, int lo, int hi) {
    if (v < lo) {
        return lo;
    }
    if (v > hi) {
        return hi;
    }
    return v;
}

/* Map dst coord to src Q8: (i+0.5)*src/dst - 0.5 */
static int64_t map_src_q8(size_t i, size_t dst, size_t src) {
    return ((int64_t)(i * 2u + 1u) * (int64_t)src * (int64_t)TA_ART_Q8_ONE) /
               (int64_t)(dst * 2u) -
           (int64_t)(TA_ART_Q8_ONE / 2);
}

static void sample_rgba(const uint8_t *img, size_t w, size_t h, int x, int y,
                        int *r, int *g, int *b, int *a) {
    x = clampi(x, 0, (int)w - 1);
    y = clampi(y, 0, (int)h - 1);
    {
        size_t j = (size_t)y * w + (size_t)x;
        *r = img[j * 4];
        *g = img[j * 4 + 1];
        *b = img[j * 4 + 2];
        *a = img[j * 4 + 3];
    }
}

int ta_artwork_box_down(const uint8_t *src, size_t sw, size_t sh, uint8_t *dst,
                        size_t dw, size_t dh) {
    size_t dy, dx;
    if (src == NULL || dst == NULL || sw == 0 || sh == 0 || dw == 0 || dh == 0) {
        return -1;
    }
    for (dy = 0; dy < dh; dy++) {
        size_t y0 = dy * sh / dh;
        size_t y1 = (dy + 1u) * sh / dh;
        if (y1 <= y0) {
            y1 = y0 + 1u;
        }
        if (y1 > sh) {
            y1 = sh;
        }
        for (dx = 0; dx < dw; dx++) {
            size_t x0 = dx * sw / dw;
            size_t x1 = (dx + 1u) * sw / dw;
            size_t yy, xx;
            uint32_t sr = 0, sg = 0, sb = 0, sa = 0, cnt = 0;
            if (x1 <= x0) {
                x1 = x0 + 1u;
            }
            if (x1 > sw) {
                x1 = sw;
            }
            for (yy = y0; yy < y1; yy++) {
                for (xx = x0; xx < x1; xx++) {
                    size_t j = yy * sw + xx;
                    sr += src[j * 4];
                    sg += src[j * 4 + 1];
                    sb += src[j * 4 + 2];
                    sa += src[j * 4 + 3];
                    cnt++;
                }
            }
            {
                size_t o = dy * dw + dx;
                if (cnt == 0) {
                    cnt = 1;
                }
                dst[o * 4] = (uint8_t)(sr / cnt);
                dst[o * 4 + 1] = (uint8_t)(sg / cnt);
                dst[o * 4 + 2] = (uint8_t)(sb / cnt);
                dst[o * 4 + 3] = (uint8_t)(sa / cnt);
            }
        }
    }
    return 0;
}

/* Horizontal quadratic pass: sw x sh -> dw x sh */
static int q8_quad_h(const uint8_t *src, size_t sw, size_t sh, uint8_t *dst,
                     size_t dw) {
    size_t y, x;
    for (y = 0; y < sh; y++) {
        for (x = 0; x < dw; x++) {
            int64_t sx_q8 = map_src_q8(x, dw, sw);
            int ix = (int)(sx_q8 / TA_ART_Q8_ONE);
            int fx = (int)(sx_q8 - (int64_t)ix * TA_ART_Q8_ONE);
            int k;
            int sum_r = 0, sum_g = 0, sum_b = 0, sum_a = 0, sum_w = 0;
            /* taps at ix-1, ix, ix+1 relative to sample position */
            for (k = -1; k <= 1; k++) {
                int d = k * TA_ART_Q8_ONE - fx;
                int w = qbspline_w_q8(d);
                int r, g, b, a;
                if (w == 0) {
                    continue;
                }
                sample_rgba(src, sw, sh, ix + k, (int)y, &r, &g, &b, &a);
                sum_r += r * w;
                sum_g += g * w;
                sum_b += b * w;
                sum_a += a * w;
                sum_w += w;
            }
            {
                size_t o = y * dw + x;
                if (sum_w <= 0) {
                    sum_w = 1;
                }
                dst[o * 4] = (uint8_t)clampi(sum_r / sum_w, 0, 255);
                dst[o * 4 + 1] = (uint8_t)clampi(sum_g / sum_w, 0, 255);
                dst[o * 4 + 2] = (uint8_t)clampi(sum_b / sum_w, 0, 255);
                dst[o * 4 + 3] = (uint8_t)clampi(sum_a / sum_w, 0, 255);
            }
        }
    }
    return 0;
}

/* Vertical quadratic pass: dw x sh -> dw x dh */
static int q8_quad_v(const uint8_t *src, size_t dw, size_t sh, uint8_t *dst,
                     size_t dh) {
    size_t y, x;
    for (y = 0; y < dh; y++) {
        int64_t sy_q8 = map_src_q8(y, dh, sh);
        int iy = (int)(sy_q8 / TA_ART_Q8_ONE);
        int fy = (int)(sy_q8 - (int64_t)iy * TA_ART_Q8_ONE);
        for (x = 0; x < dw; x++) {
            int k;
            int sum_r = 0, sum_g = 0, sum_b = 0, sum_a = 0, sum_w = 0;
            for (k = -1; k <= 1; k++) {
                int d = k * TA_ART_Q8_ONE - fy;
                int w = qbspline_w_q8(d);
                int r, g, b, a;
                if (w == 0) {
                    continue;
                }
                sample_rgba(src, dw, sh, (int)x, iy + k, &r, &g, &b, &a);
                sum_r += r * w;
                sum_g += g * w;
                sum_b += b * w;
                sum_a += a * w;
                sum_w += w;
            }
            {
                size_t o = y * dw + x;
                if (sum_w <= 0) {
                    sum_w = 1;
                }
                dst[o * 4] = (uint8_t)clampi(sum_r / sum_w, 0, 255);
                dst[o * 4 + 1] = (uint8_t)clampi(sum_g / sum_w, 0, 255);
                dst[o * 4 + 2] = (uint8_t)clampi(sum_b / sum_w, 0, 255);
                dst[o * 4 + 3] = (uint8_t)clampi(sum_a / sum_w, 0, 255);
            }
        }
    }
    return 0;
}

int ta_artwork_q8_quad_uprez(const uint8_t *src, size_t sw, size_t sh,
                             uint8_t *dst, size_t dw, size_t dh) {
    uint8_t *tmp;
    if (src == NULL || dst == NULL || sw == 0 || sh == 0 || dw == 0 || dh == 0) {
        return -1;
    }
    tmp = (uint8_t *)malloc(dw * sh * 4u);
    if (tmp == NULL) {
        return -1;
    }
    if (q8_quad_h(src, sw, sh, tmp, dw) != 0) {
        free(tmp);
        return -1;
    }
    if (q8_quad_v(tmp, dw, sh, dst, dh) != 0) {
        free(tmp);
        return -1;
    }
    free(tmp);
    return 0;
}

/* Build normalized Q8 Gaussian 1D kernel; returns radius, fills w[0..2r]. */
static int build_gauss_kernel(int sigma_q8, int *w, int max_r) {
    int r;
    int i;
    int sum = 0;
    if (sigma_q8 < 1) {
        sigma_q8 = 1;
    }
    /* radius ~ 3*sigma */
    r = (3 * sigma_q8 + TA_ART_Q8_ONE - 1) / TA_ART_Q8_ONE;
    if (r < 1) {
        r = 1;
    }
    if (r > max_r) {
        r = max_r;
    }
    for (i = -r; i <= r; i++) {
        int64_t x_q8 = (int64_t)i * TA_ART_Q8_ONE;
        int64_t num = x_q8 * x_q8;
        int64_t den = 2 * (int64_t)sigma_q8 * (int64_t)sigma_q8;
        double t = (double)num / (double)den;
        double e = exp(-t);
        w[i + r] = (int)(e * (double)TA_ART_Q8_ONE + 0.5);
        sum += w[i + r];
    }
    if (sum <= 0) {
        w[r] = TA_ART_Q8_ONE;
        sum = TA_ART_Q8_ONE;
    }
    /* renormalize to sum TA_ART_Q8_ONE */
    {
        int acc = 0;
        for (i = 0; i < 2 * r; i++) {
            w[i] = (w[i] * TA_ART_Q8_ONE) / sum;
            acc += w[i];
        }
        w[2 * r] = TA_ART_Q8_ONE - acc;
    }
    return r;
}

int ta_artwork_gauss_rgba(uint8_t *rgba, size_t w, size_t h, int sigma_q8) {
    int kw[64];
    int r;
    uint8_t *tmp;
    size_t n;
    size_t y, x;
    int k;

    if (rgba == NULL || w == 0 || h == 0) {
        return -1;
    }
    r = build_gauss_kernel(sigma_q8, kw, 31);
    n = w * h;
    tmp = (uint8_t *)malloc(n * 4u);
    if (tmp == NULL) {
        return -1;
    }
    /* horizontal */
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            int sum_r = 0, sum_g = 0, sum_b = 0, sum_a = 0, sum_w = 0;
            for (k = -r; k <= r; k++) {
                int ww = kw[k + r];
                int rr, gg, bb, aa;
                sample_rgba(rgba, w, h, (int)x + k, (int)y, &rr, &gg, &bb, &aa);
                sum_r += rr * ww;
                sum_g += gg * ww;
                sum_b += bb * ww;
                sum_a += aa * ww;
                sum_w += ww;
            }
            {
                size_t o = y * w + x;
                if (sum_w <= 0) {
                    sum_w = 1;
                }
                tmp[o * 4] = (uint8_t)clampi(sum_r / sum_w, 0, 255);
                tmp[o * 4 + 1] = (uint8_t)clampi(sum_g / sum_w, 0, 255);
                tmp[o * 4 + 2] = (uint8_t)clampi(sum_b / sum_w, 0, 255);
                tmp[o * 4 + 3] = (uint8_t)clampi(sum_a / sum_w, 0, 255);
            }
        }
    }
    /* vertical */
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            int sum_r = 0, sum_g = 0, sum_b = 0, sum_a = 0, sum_w = 0;
            for (k = -r; k <= r; k++) {
                int ww = kw[k + r];
                int rr, gg, bb, aa;
                sample_rgba(tmp, w, h, (int)x, (int)y + k, &rr, &gg, &bb, &aa);
                sum_r += rr * ww;
                sum_g += gg * ww;
                sum_b += bb * ww;
                sum_a += aa * ww;
                sum_w += ww;
            }
            {
                size_t o = y * w + x;
                if (sum_w <= 0) {
                    sum_w = 1;
                }
                rgba[o * 4] = (uint8_t)clampi(sum_r / sum_w, 0, 255);
                rgba[o * 4 + 1] = (uint8_t)clampi(sum_g / sum_w, 0, 255);
                rgba[o * 4 + 2] = (uint8_t)clampi(sum_b / sum_w, 0, 255);
                rgba[o * 4 + 3] = (uint8_t)clampi(sum_a / sum_w, 0, 255);
            }
        }
    }
    free(tmp);
    return 0;
}

static int gauss_sample_1d(const uint8_t *src, size_t sw, size_t sh, int fixed,
                           int along_x, int64_t s_q8, int sigma_q8, int *r,
                           int *g, int *b, int *a) {
    int rad;
    int ix = (int)(s_q8 / TA_ART_Q8_ONE);
    int fx = (int)(s_q8 - (int64_t)ix * TA_ART_Q8_ONE);
    int k;
    int sum_r = 0, sum_g = 0, sum_b = 0, sum_a = 0, sum_w = 0;
    if (sigma_q8 < 1) {
        sigma_q8 = 1;
    }
    rad = (3 * sigma_q8 + TA_ART_Q8_ONE - 1) / TA_ART_Q8_ONE;
    if (rad < 1) {
        rad = 1;
    }
    if (rad > 31) {
        rad = 31;
    }
    for (k = -rad; k <= rad; k++) {
        int d = k * TA_ART_Q8_ONE - fx;
        int ww;
        int rr, gg, bb, aa;
        {
            int64_t num = (int64_t)d * (int64_t)d;
            int64_t den = 2 * (int64_t)sigma_q8 * (int64_t)sigma_q8;
            double t = (double)num / (double)den;
            ww = (int)(exp(-t) * (double)TA_ART_Q8_ONE + 0.5);
        }
        if (ww == 0) {
            continue;
        }
        if (along_x) {
            sample_rgba(src, sw, sh, ix + k, fixed, &rr, &gg, &bb, &aa);
        } else {
            sample_rgba(src, sw, sh, fixed, ix + k, &rr, &gg, &bb, &aa);
        }
        sum_r += rr * ww;
        sum_g += gg * ww;
        sum_b += bb * ww;
        sum_a += aa * ww;
        sum_w += ww;
    }
    if (sum_w <= 0) {
        sum_w = 1;
    }
    *r = sum_r / sum_w;
    *g = sum_g / sum_w;
    *b = sum_b / sum_w;
    *a = sum_a / sum_w;
    return 0;
}

int ta_artwork_gauss_uprez(const uint8_t *src, size_t sw, size_t sh,
                           uint8_t *dst, size_t dw, size_t dh,
                           int sigma_src_q8) {
    uint8_t *tmp;
    size_t y, x;
    if (src == NULL || dst == NULL || sw == 0 || sh == 0 || dw == 0 || dh == 0) {
        return -1;
    }
    if (sigma_src_q8 < 1) {
        sigma_src_q8 = TA_ART_Q8_ONE / 2;
    }
    tmp = (uint8_t *)malloc(dw * sh * 4u);
    if (tmp == NULL) {
        return -1;
    }
    /* horizontal: sw x sh -> dw x sh */
    for (y = 0; y < sh; y++) {
        for (x = 0; x < dw; x++) {
            int64_t sx_q8 = map_src_q8(x, dw, sw);
            int r, g, b, a;
            gauss_sample_1d(src, sw, sh, (int)y, 1, sx_q8, sigma_src_q8, &r, &g,
                            &b, &a);
            {
                size_t o = y * dw + x;
                tmp[o * 4] = (uint8_t)clampi(r, 0, 255);
                tmp[o * 4 + 1] = (uint8_t)clampi(g, 0, 255);
                tmp[o * 4 + 2] = (uint8_t)clampi(b, 0, 255);
                tmp[o * 4 + 3] = (uint8_t)clampi(a, 0, 255);
            }
        }
    }
    /* vertical: dw x sh -> dw x dh */
    for (y = 0; y < dh; y++) {
        int64_t sy_q8 = map_src_q8(y, dh, sh);
        for (x = 0; x < dw; x++) {
            int r, g, b, a;
            /* along_x=0: fixed_y arg is x, sample varies in y */
            gauss_sample_1d(tmp, dw, sh, (int)x, 0, sy_q8, sigma_src_q8, &r, &g,
                            &b, &a);
            {
                size_t o = y * dw + x;
                dst[o * 4] = (uint8_t)clampi(r, 0, 255);
                dst[o * 4 + 1] = (uint8_t)clampi(g, 0, 255);
                dst[o * 4 + 2] = (uint8_t)clampi(b, 0, 255);
                dst[o * 4 + 3] = (uint8_t)clampi(a, 0, 255);
            }
        }
    }
    free(tmp);
    return 0;
}

uint64_t ta_artwork_rgb_sumsq(const uint8_t *a, const uint8_t *b, size_t n_px) {
    uint64_t s = 0;
    size_t i;
    if (a == NULL || b == NULL) {
        return 0;
    }
    for (i = 0; i < n_px; i++) {
        int dr = (int)a[i * 4] - (int)b[i * 4];
        int dg = (int)a[i * 4 + 1] - (int)b[i * 4 + 1];
        int db = (int)a[i * 4 + 2] - (int)b[i * 4 + 2];
        s += (uint64_t)(dr * dr + dg * dg + db * db);
    }
    return s;
}

static void desat_inplace(uint8_t *rgba, size_t n) {
    size_t i;
    for (i = 0; i < n; i++) {
        int r = rgba[i * 4];
        int g = rgba[i * 4 + 1];
        int b = rgba[i * 4 + 2];
        int gray = (r + g + b) / 3;
        rgba[i * 4] = (uint8_t)((r * 3 + gray) / 4);
        rgba[i * 4 + 1] = (uint8_t)((g * 3 + gray) / 4);
        rgba[i * 4 + 2] = (uint8_t)((b * 3 + gray) / 4);
    }
}

static void calm_box3(uint8_t *rgba, size_t w, size_t h) {
    size_t n = w * h;
    size_t i;
    uint8_t *tmp = (uint8_t *)malloc(n * 4u);
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
            rgba[i * 4] = (uint8_t)(sum_r / cnt);
            rgba[i * 4 + 1] = (uint8_t)(sum_g / cnt);
            rgba[i * 4 + 2] = (uint8_t)(sum_b / cnt);
        }
    }
    free(tmp);
    desat_inplace(rgba, n);
}

void ta_artwork_calm_rgba(uint8_t *rgba, size_t w, size_t h) {
    uint8_t *lo;
    uint8_t *up;
    size_t edge;

    if (rgba == NULL || w == 0 || h == 0) {
        return;
    }
    edge = w < h ? w : h;
    if (edge < (size_t)TA_ART_LORES) {
        calm_box3(rgba, w, h);
        return;
    }
    lo = (uint8_t *)malloc((size_t)TA_ART_LORES * (size_t)TA_ART_LORES * 4u);
    up = (uint8_t *)malloc(w * h * 4u);
    if (lo == NULL || up == NULL) {
        free(lo);
        free(up);
        calm_box3(rgba, w, h);
        return;
    }
    if (ta_artwork_box_down(rgba, w, h, lo, TA_ART_LORES, TA_ART_LORES) != 0 ||
        ta_artwork_q8_quad_uprez(lo, TA_ART_LORES, TA_ART_LORES, up, w, h) !=
            0) {
        free(lo);
        free(up);
        calm_box3(rgba, w, h);
        return;
    }
    memcpy(rgba, up, w * h * 4u);
    free(lo);
    free(up);
    desat_inplace(rgba, w * h);
}

int ta_artwork_is_default(uint32_t fingerprint) {
    return fingerprint == TA_ART_DEFAULT_FP;
}

int ta_artwork_on_album_change(const char *net_dst, const char *draw_dst,
                               ta_session_id_t session, uint32_t time_remain_ms) {
    if (net_dst == NULL || draw_dst == NULL) {
        return -1;
    }
    if (ta_sched_arm_oneshot(net_dst, session, 50, TA_EV_NET_POLL) != 0) {
        return -1;
    }
    if (time_remain_ms == 0) {
        time_remain_ms = 1000;
    }
    if (ta_sched_arm_oneshot(draw_dst, session, time_remain_ms,
                             TA_EV_DRAW_UPDATE) != 0) {
        return -1;
    }
    return 0;
}
