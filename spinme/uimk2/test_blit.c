/* Correctness for tiled src-over. Base alpha is always 0: after blit,
 * dst must equal src. Also checks a non-zero base against the pixel ref. */
#include "uimk2_blit.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define W PANEL_W
#define H PANEL_H
#define BYTES (W * H * 4u)

static int failures;

static void expect(int cond, const char *msg) {
    if (!cond) {
        fprintf(stderr, "FAIL %s\n", msg);
        failures++;
    }
}

static void fill_src(uint8_t *src) {
    uint32_t i;
    for (i = 0; i < W * H; i++) {
        src[i * 4u + 0u] = (uint8_t)((i * 3u) & 255u);
        src[i * 4u + 1u] = (uint8_t)((i * 5u) & 255u);
        src[i * 4u + 2u] = (uint8_t)((i * 7u) & 255u);
        src[i * 4u + 3u] = (uint8_t)((i * 11u) & 255u);
    }
}

static void ref_blit(uint8_t *dst, const uint8_t *src, uint32_t w, uint32_t h) {
    uint32_t y;
    uint32_t x;
    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            uint32_t off = (y * W + x) * 4u;
            uimk2_blit_src_over_pixel(dst + off, src + off);
        }
    }
}

int main(void) {
    uint8_t *src = (uint8_t *)malloc(BYTES);
    uint8_t *dst = (uint8_t *)malloc(BYTES);
    uint8_t *ref = (uint8_t *)malloc(BYTES);
    uint32_t tiles[] = {8u, 16u, 20u, 24u, 30u, 32u, 36u, 40u, 45u, 60u};
    size_t t;
    expect(src != NULL && dst != NULL && ref != NULL, "malloc");
    if (src == NULL || dst == NULL || ref == NULL) {
        return 1;
    }
    fill_src(src);

    /* Base A=0: result must equal src for every tile size. */
    for (t = 0; t < sizeof tiles / sizeof tiles[0]; t++) {
        uint32_t tw = tiles[t];
        memset(dst, 0, BYTES);
        uimk2_blit_src_over(dst, W, src, W, W, H, tw, tw);
        expect(memcmp(dst, src, BYTES) == 0, "clear-base equals src");
    }

    /* Non-zero base vs pixel reference, default TILE_W x TILE_H. */
    fill_src(src);
    memset(dst, 0x5a, BYTES);
    memset(ref, 0x5a, BYTES);
    ref_blit(ref, src, W, H);
    uimk2_blit_src_over(dst, W, src, W, W, H, TILE_W, TILE_H);
    expect(memcmp(dst, ref, BYTES) == 0, "tiled matches pixel ref");

    /* Working-set constant is sane for a 32 KB D-cache. */
    expect(UIMK2_BLIT_TILE_WORKING_BYTES <= 32u * 1024u,
           "default tile working set fits 32KB D-cache");

    /* Packed 6+6+6 / 2-bit A: clear base copies src; mid-alpha uses
     * add/shift then >>2 & mask on a covered base. */
    {
        uint32_t *ps = (uint32_t *)malloc(W * H * sizeof(uint32_t));
        uint32_t *pd = (uint32_t *)malloc(W * H * sizeof(uint32_t));
        uint32_t i;
        uint8_t rgba[4];
        uint32_t got;
        expect(ps != NULL && pd != NULL, "malloc66");
        if (ps != NULL && pd != NULL) {
            for (i = 0; i < W * H; i++) {
                ps[i] = uimk2_blit_pack66(src + i * 4u);
            }
            memset(pd, 0, W * H * sizeof(uint32_t));
            uimk2_blit_src_over66(pd, W, ps, W, W, H, TILE_W, TILE_H);
            {
                int bad = 0;
                for (i = 0; i < W * H; i++) {
                    unsigned a = (ps[i] >> UIMK2_BLIT_A2_SHIFT) & 3u;
                    /* a2==0 is transparent: clear base stays 0. Else copy. */
                    uint32_t want = a == 0u ? 0u : ps[i];
                    if (pd[i] != want) {
                        bad = 1;
                        break;
                    }
                }
                expect(!bad, "pack66 clear-base");
            }

            /* a=1 over opaque white-ish: (3*d + s)>>2 & mask */
            rgba[0] = 255;
            rgba[1] = 255;
            rgba[2] = 255;
            rgba[3] = 255;
            pd[0] = uimk2_blit_pack66(rgba);
            rgba[0] = 0;
            rgba[1] = 0;
            rgba[2] = 0;
            rgba[3] = 85; /* a2 == 1 */
            ps[0] = uimk2_blit_pack66(rgba);
            got = uimk2_blit_lerp66(pd[0], ps[0]);
            {
                uint32_t d = pd[0] & UIMK2_BLIT_RGB6_MASK;
                uint32_t s = ps[0] & UIMK2_BLIT_RGB6_MASK;
                uint32_t want = ((d + (d << 1) + s) >> 2) & UIMK2_BLIT_RGB6_MASK;
                expect((got & UIMK2_BLIT_RGB6_MASK) == want, "pack66 a1 shift-mask");
            }
            expect(((got >> UIMK2_BLIT_A2_SHIFT) & 3u) == 3u,
                   "pack66 a1 keeps strong alpha");

            /* Transparent skip run: 5 clear, then opaque, then clear. */
            {
                uint32_t row[8];
                uint8_t clear[4] = {0, 0, 0, 0};
                uint8_t ink[4] = {255, 0, 0, 255};
                uint32_t j;
                for (j = 0; j < 5; j++) {
                    row[j] = uimk2_blit_pack66(clear);
                }
                row[5] = uimk2_blit_pack66(ink);
                row[6] = uimk2_blit_pack66(clear);
                row[7] = uimk2_blit_pack66(clear);
                uimk2_blit_encode_row_skips(row, 8);
                expect(uimk2_blit_is_skip66(row[0]) &&
                           uimk2_blit_skip66(row[0]) == 5u,
                       "skip run of 5");
                expect(!uimk2_blit_is_skip66(row[5]), "ink stays packed");
                expect(uimk2_blit_is_skip66(row[6]) &&
                           uimk2_blit_skip66(row[6]) == 2u,
                       "trailing skip of 2");
                memset(pd, 0x11, 8 * sizeof(uint32_t));
                uimk2_blit_src_over66(pd, 8, row, 8, 8, 1, 8, 1);
                expect(pd[0] == 0x11111111u && pd[4] == 0x11111111u,
                       "skip leaves dst");
                expect(pd[5] == row[5], "ink blitted");
            }
        }
        free(ps);
        free(pd);
    }

    free(src);
    free(dst);
    free(ref);
    if (failures != 0) {
        fprintf(stderr, "%d failure(s)\n", failures);
        return 1;
    }
    puts("ok");
    return 0;
}
