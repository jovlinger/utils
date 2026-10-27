/* Host blit bench: 8888 vs pack66 (with row skip-RLE) vs sparse text-like.
 * N=100, -O2.
 */
#include "bench_time.h"
#include "uimk2_blit.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define BENCH_N 100
#define BENCH_WARMUP 8
#define W PANEL_W
#define H PANEL_H
#define NPIX (W * H)
#define BYTES (NPIX * 4u)

static void fill_rgba_dense(uint8_t *src) {
    uint32_t i;
    for (i = 0; i < NPIX; i++) {
        src[i * 4u + 0u] = (uint8_t)((i * 3u) & 255u);
        src[i * 4u + 1u] = (uint8_t)((i * 5u) & 255u);
        src[i * 4u + 2u] = (uint8_t)((i * 7u) & 255u);
        src[i * 4u + 3u] = (uint8_t)((i * 11u) & 255u);
    }
}

/* Mostly transparent rows with short opaque ink runs -- glyph-like. */
static void fill_rgba_sparse(uint8_t *src) {
    uint32_t y;
    uint32_t x;
    memset(src, 0, BYTES);
    for (y = 0; y < H; y++) {
        for (x = 0; x < W; x++) {
            uint32_t i = y * W + x;
            /* ~1/12 of pixels are ink clusters of width 2 */
            if ((x % 12u) == 3u || (x % 12u) == 4u) {
                src[i * 4u + 0u] = 200;
                src[i * 4u + 1u] = 100;
                src[i * 4u + 2u] = 50;
                src[i * 4u + 3u] = 255;
            }
        }
    }
}

static void pack_rows(uint32_t *dst, const uint8_t *rgba) {
    uint32_t y;
    for (y = 0; y < H; y++) {
        uimk2_blit_rgba_row_to_pack66(dst + y * W, rgba + y * W * 4u, W);
    }
}

static void emit(const char *tag, uint32_t tw, int correct, const double *us) {
    bench_stats st;
    stats_of(us, BENCH_N, &st);
    printf("BENCH %s tile=%ux%u correct=%d mean_us=%.2f stdev_us=%.2f "
           "cv_pct=%.2f min_us=%.2f max_us=%.2f\n",
           tag, tw, tw, correct, st.mean_us, st.stdev_us,
           st.mean_us > 0.0 ? 100.0 * st.stdev_us / st.mean_us : 0.0, st.min_us,
           st.max_us);
}

static int check_clear66(const uint32_t *dst, const uint32_t *src) {
    uint32_t y;
    for (y = 0; y < H; y++) {
        uint32_t x = 0;
        while (x < W) {
            uint32_t s = src[y * W + x];
            if (uimk2_blit_is_skip66(s)) {
                uint32_t skip = uimk2_blit_skip66(s);
                uint32_t k;
                if (skip > W - x) {
                    skip = W - x;
                }
                for (k = 0; k < skip; k++) {
                    if (dst[y * W + x + k] != 0u) {
                        return 0;
                    }
                }
                x += skip;
                continue;
            }
            if (dst[y * W + x] != s) {
                return 0;
            }
            x++;
        }
    }
    return 1;
}

static void time_8888(uint8_t *dst8, const uint8_t *src8, uint32_t tw,
                      double *us, volatile uint32_t *sink) {
    int i;
    for (i = 0; i < BENCH_WARMUP; i++) {
        memset(dst8, 0, BYTES);
        uimk2_blit_src_over(dst8, W, src8, W, W, H, tw, tw);
        *sink += dst8[0];
    }
    for (i = 0; i < BENCH_N; i++) {
        uint64_t t0;
        uint64_t t1;
        memset(dst8, 0, BYTES);
        t0 = mono_ticks();
        uimk2_blit_src_over(dst8, W, src8, W, W, H, tw, tw);
        t1 = mono_ticks();
        us[i] = ticks_to_us(t1 - t0);
        *sink += dst8[i & 255];
    }
}

static void time_66_clear(uint32_t *dst66, const uint32_t *src66, uint32_t tw,
                          double *us, volatile uint32_t *sink) {
    int i;
    for (i = 0; i < BENCH_WARMUP; i++) {
        memset(dst66, 0, NPIX * sizeof(uint32_t));
        uimk2_blit_src_over66(dst66, W, src66, W, W, H, tw, tw);
        *sink += dst66[0];
    }
    for (i = 0; i < BENCH_N; i++) {
        uint64_t t0;
        uint64_t t1;
        memset(dst66, 0, NPIX * sizeof(uint32_t));
        t0 = mono_ticks();
        uimk2_blit_src_over66(dst66, W, src66, W, W, H, tw, tw);
        t1 = mono_ticks();
        us[i] = ticks_to_us(t1 - t0);
        *sink += dst66[i & 255];
    }
}

int main(void) {
    uint8_t *src8;
    uint8_t *dst8;
    uint32_t *src66;
    uint32_t *dst66;
    double us[BENCH_N];
    uint32_t tw = TILE_W;
    int ok;
    volatile uint32_t sink = 0;

    clock_init();
    src8 = (uint8_t *)malloc(BYTES);
    dst8 = (uint8_t *)malloc(BYTES);
    src66 = (uint32_t *)malloc(NPIX * sizeof(uint32_t));
    dst66 = (uint32_t *)malloc(NPIX * sizeof(uint32_t));
    if (src8 == NULL || dst8 == NULL || src66 == NULL || dst66 == NULL) {
        fprintf(stderr, "malloc failed\n");
        return 1;
    }

    printf("BENCH blit host panel=%ux%u tile=%u n=%d clock=%s\n", W, H, tw,
           BENCH_N, clock_name());

    /* Dense pattern (historical compare). */
    fill_rgba_dense(src8);
    pack_rows(src66, src8);
    memset(dst8, 0, BYTES);
    uimk2_blit_src_over(dst8, W, src8, W, W, H, tw, tw);
    ok = memcmp(dst8, src8, BYTES) == 0;
    time_8888(dst8, src8, tw, us, &sink);
    emit("blit_src_over_8888_dense_clear", tw, ok, us);

    memset(dst66, 0, NPIX * sizeof(uint32_t));
    uimk2_blit_src_over66(dst66, W, src66, W, W, H, tw, tw);
    ok = check_clear66(dst66, src66);
    time_66_clear(dst66, src66, tw, us, &sink);
    emit("blit_src_over66_dense_clear", tw, ok, us);

    /* Sparse / text-like. */
    fill_rgba_sparse(src8);
    pack_rows(src66, src8);
    memset(dst8, 0, BYTES);
    uimk2_blit_src_over(dst8, W, src8, W, W, H, tw, tw);
    ok = memcmp(dst8, src8, BYTES) == 0;
    time_8888(dst8, src8, tw, us, &sink);
    emit("blit_src_over_8888_sparse_clear", tw, ok, us);

    memset(dst66, 0, NPIX * sizeof(uint32_t));
    uimk2_blit_src_over66(dst66, W, src66, W, W, H, tw, tw);
    ok = check_clear66(dst66, src66);
    time_66_clear(dst66, src66, tw, us, &sink);
    emit("blit_src_over66_sparse_clear", tw, ok, us);

    printf("sink=%u\n", (unsigned)sink);
    free(src8);
    free(dst8);
    free(src66);
    free(dst66);
    return ok ? 0 : 1;
}
