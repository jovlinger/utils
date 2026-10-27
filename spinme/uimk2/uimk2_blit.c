#include "uimk2_blit.h"

#include <stdint.h>
#include <string.h>

#if defined(CONFIG_IDF_TARGET_ESP32S3)
void uimk2_pie_load16(const void *mem, void *out16);
void uimk2_pie_store16(void *mem, const void *in16);
#else
static void uimk2_pie_load16(const void *mem, void *out16) {
    memcpy(out16, mem, 16u);
}
static void uimk2_pie_store16(void *mem, const void *in16) {
    memcpy(mem, in16, 16u);
}
#endif

/* Straight src-over into dst. Integer channels 0..255.
 * out_a = sa + da*(255-sa)/255
 * out_c = (sc*sa + dc*da*(255-sa)/255) / out_a   when out_a != 0
 * When the base has alpha 0, this equals a copy of src (correctness case). */
void uimk2_blit_src_over_pixel(uint8_t *dst, const uint8_t *src) {
    unsigned sa = src[3];
    unsigned da = dst[3];
    unsigned inv = 255u - sa;
    unsigned out_a = sa + (da * inv) / 255u;
    unsigned c;
    if (out_a == 0u) {
        dst[0] = 0;
        dst[1] = 0;
        dst[2] = 0;
        dst[3] = 0;
        return;
    }
    for (c = 0; c < 3u; c++) {
        unsigned sc = src[c];
        unsigned dc = dst[c];
        unsigned num = sc * sa + (dc * da * inv) / 255u;
        dst[c] = (uint8_t)(num / out_a);
    }
    dst[3] = (uint8_t)out_a;
}

void uimk2_blit_src_over_tile(uint8_t *dst, uint32_t dst_stride_px,
                              const uint8_t *src, uint32_t src_stride_px,
                              uint32_t x0, uint32_t y0, uint32_t tw,
                              uint32_t th) {
    uint32_t y;
    uint32_t x;
    for (y = 0; y < th; y++) {
        uint32_t dy = y0 + y;
        uint8_t *drow = dst + (dy * dst_stride_px + x0) * 4u;
        const uint8_t *srow = src + (dy * src_stride_px + x0) * 4u;
        for (x = 0; x < tw; x++) {
            uimk2_blit_src_over_pixel(drow + x * 4u, srow + x * 4u);
        }
    }
}

void uimk2_blit_src_over(uint8_t *dst, uint32_t dst_stride_px,
                         const uint8_t *src, uint32_t src_stride_px,
                         uint32_t w, uint32_t h, uint32_t tile_w,
                         uint32_t tile_h) {
    uint32_t y0;
    uint32_t x0;
    if (tile_w == 0u || tile_h == 0u || w == 0u || h == 0u) {
        return;
    }
    for (y0 = 0; y0 < h; y0 += tile_h) {
        uint32_t th = tile_h;
        if (y0 + th > h) {
            th = h - y0;
        }
        for (x0 = 0; x0 < w; x0 += tile_w) {
            uint32_t tw = tile_w;
            if (x0 + tw > w) {
                tw = w - x0;
            }
            uimk2_blit_src_over_tile(dst, dst_stride_px, src, src_stride_px, x0,
                                     y0, tw, th);
        }
    }
}

uint32_t uimk2_blit_pack66(const uint8_t rgba[4]) {
    uint32_t a = (uint32_t)rgba[3] >> 6;
    uint32_t r;
    uint32_t g;
    uint32_t b;
    if (a == 0u) {
        /* Transparent: skip 1 word until encode_row_skips coalesces. */
        return 1u;
    }
    r = (uint32_t)rgba[0] >> 2;
    g = (uint32_t)rgba[1] >> 2;
    b = (uint32_t)rgba[2] >> 2;
    return r | (g << 8) | (b << 16) | (a << UIMK2_BLIT_A2_SHIFT);
}

void uimk2_blit_unpack66(uint32_t p, uint8_t rgba[4]) {
    uint32_t r;
    uint32_t g;
    uint32_t b;
    uint32_t a;
    if (uimk2_blit_is_skip66(p)) {
        rgba[0] = 0;
        rgba[1] = 0;
        rgba[2] = 0;
        rgba[3] = 0;
        return;
    }
    r = p & 0x3Fu;
    g = (p >> 8) & 0x3Fu;
    b = (p >> 16) & 0x3Fu;
    a = (p >> UIMK2_BLIT_A2_SHIFT) & 0x3u;
    rgba[0] = (uint8_t)((r << 2) | (r >> 4));
    rgba[1] = (uint8_t)((g << 2) | (g >> 4));
    rgba[2] = (uint8_t)((b << 2) | (b >> 4));
    rgba[3] = (uint8_t)(a * 85u);
}

void uimk2_blit_encode_row_skips(uint32_t *row, uint32_t w) {
    uint32_t x = 0;
    while (x < w) {
        uint32_t start;
        uint32_t len;
        if (!uimk2_blit_is_skip66(row[x])) {
            x++;
            continue;
        }
        start = x;
        while (x < w && uimk2_blit_is_skip66(row[x])) {
            x++;
        }
        len = x - start;
        if (len > UIMK2_BLIT_SKIP_MASK) {
            len = UIMK2_BLIT_SKIP_MASK;
        }
        row[start] = len;
    }
}

void uimk2_blit_rgba_row_to_pack66(uint32_t *dst, const uint8_t *rgba,
                                   uint32_t w) {
    uint32_t x;
    for (x = 0; x < w; x++) {
        dst[x] = uimk2_blit_pack66(rgba + x * 4u);
    }
    uimk2_blit_encode_row_skips(dst, w);
}

uint32_t uimk2_blit_lerp66(uint32_t dst, uint32_t src) {
    unsigned a;
    unsigned da;
    uint32_t d;
    uint32_t s;
    uint32_t rgb;
    unsigned out_a;
    if (uimk2_blit_is_skip66(src)) {
        return dst;
    }
    a = (src >> UIMK2_BLIT_A2_SHIFT) & 0x3u;
    da = uimk2_blit_is_skip66(dst)
             ? 0u
             : ((dst >> UIMK2_BLIT_A2_SHIFT) & 0x3u);
    d = dst & UIMK2_BLIT_RGB6_MASK;
    s = src & UIMK2_BLIT_RGB6_MASK;
    if (da == 0u || a == 3u) {
        return src;
    }
    if (a == 1u) {
        rgb = (d + (d << 1) + s) >> 2;
        rgb &= UIMK2_BLIT_RGB6_MASK;
    } else {
        rgb = (d + s) >> 1;
        rgb &= UIMK2_BLIT_RGB6_MASK;
    }
    out_a = a > da ? a : da;
    return rgb | ((uint32_t)out_a << UIMK2_BLIT_A2_SHIFT);
}

/* Skip-aware span. Opaque runs of 4 use PIE/memcpy; skips jump in words. */
static void blit_span66(uint32_t *dst, const uint32_t *src, uint32_t n) {
    uint32_t s4[4] __attribute__((aligned(16)));
    uint32_t d4[4] __attribute__((aligned(16)));

    while (n > 0u) {
        uint32_t s0 = *src;
        uint32_t run;
        uint32_t k;
        if (uimk2_blit_is_skip66(s0)) {
            uint32_t skip = uimk2_blit_skip66(s0);
            if (skip > n) {
                skip = n;
            }
            dst += skip;
            src += skip;
            n -= skip;
            continue;
        }
        /* Opaque/mid-alpha run until a skip or end. */
        run = 0;
        while (run < n && !uimk2_blit_is_skip66(src[run])) {
            run++;
        }
        while (run >= 4u &&
               ((((uintptr_t)dst) | ((uintptr_t)src)) & 15u) == 0u) {
            uimk2_pie_load16(src, s4);
            uimk2_pie_load16(dst, d4);
            d4[0] = uimk2_blit_lerp66(d4[0], s4[0]);
            d4[1] = uimk2_blit_lerp66(d4[1], s4[1]);
            d4[2] = uimk2_blit_lerp66(d4[2], s4[2]);
            d4[3] = uimk2_blit_lerp66(d4[3], s4[3]);
            uimk2_pie_store16(dst, d4);
            dst += 4;
            src += 4;
            n -= 4;
            run -= 4;
        }
        for (k = 0; k < run; k++) {
            *dst = uimk2_blit_lerp66(*dst, *src);
            dst++;
            src++;
            n--;
        }
    }
}

static void blit_tile66(uint32_t *dst, uint32_t dst_stride_px,
                        const uint32_t *src, uint32_t src_stride_px,
                        uint32_t x0, uint32_t y0, uint32_t tw, uint32_t th) {
    uint32_t y;
    for (y = 0; y < th; y++) {
        uint32_t dy = y0 + y;
        blit_span66(dst + dy * dst_stride_px + x0,
                    src + dy * src_stride_px + x0, tw);
    }
}

void uimk2_blit_src_over66(uint32_t *dst, uint32_t dst_stride_px,
                           const uint32_t *src, uint32_t src_stride_px,
                           uint32_t w, uint32_t h, uint32_t tile_w,
                           uint32_t tile_h) {
    uint32_t y0;
    uint32_t x0;
    if (tile_w == 0u || tile_h == 0u || w == 0u || h == 0u) {
        return;
    }
    for (y0 = 0; y0 < h; y0 += tile_h) {
        uint32_t th = tile_h;
        if (y0 + th > h) {
            th = h - y0;
        }
        for (x0 = 0; x0 < w; x0 += tile_w) {
            uint32_t tw = tile_w;
            if (x0 + tw > w) {
                tw = w - x0;
            }
            blit_tile66(dst, dst_stride_px, src, src_stride_px, x0, y0, tw, th);
        }
    }
}
