/* Host: calm Q8 uprez, default-art suppress, album-change oneshots. */
#include "ta_artwork.h"
#include "ta_draw_events.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_sched_events.h"

#include <stdio.h>
#include <stdlib.h>
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

static int g_poll;
static int g_upd;

static int net_sink(const ta_event_t *ev) {
    if (ev->type == TA_EV_NET_POLL) {
        g_poll++;
    }
    return 0;
}

static int draw_sink(const ta_event_t *ev) {
    if (ev->type == TA_EV_DRAW_UPDATE) {
        g_upd++;
    }
    return 0;
}

static void fill_synth(uint8_t *rgba, size_t n) {
    size_t y, x;
    for (y = 0; y < n; y++) {
        for (x = 0; x < n; x++) {
            size_t o = y * n + x;
            int v = (int)((x * 200) / n);
            int band = (x > n / 2) ? 40 : 0;
            rgba[o * 4] = (uint8_t)(v + band);
            rgba[o * 4 + 1] = (uint8_t)((y * 180) / n);
            rgba[o * 4 + 2] = (uint8_t)(120 - band / 2);
            rgba[o * 4 + 3] = 255;
        }
    }
}

/* Q8 uprez must differ from nearest-neighbor (softer across the mid edge). */
static void test_q8_vs_nearest(void) {
    const size_t N = 360;
    const size_t L = TA_ART_LORES;
    uint8_t *src;
    uint8_t *lo;
    uint8_t *q8;
    uint8_t *nn;
    uint64_t sum;
    size_t n_px = N * N;
    size_t y, x;

    src = (uint8_t *)malloc(n_px * 4u);
    lo = (uint8_t *)malloc(L * L * 4u);
    q8 = (uint8_t *)malloc(n_px * 4u);
    nn = (uint8_t *)malloc(n_px * 4u);
    CHECK(src && lo && q8 && nn);
    if (!src || !lo || !q8 || !nn) {
        free(src);
        free(lo);
        free(q8);
        free(nn);
        return;
    }

    fill_synth(src, N);
    CHECK(ta_artwork_box_down(src, N, N, lo, L, L) == 0);
    CHECK(ta_artwork_q8_quad_uprez(lo, L, L, q8, N, N) == 0);
    for (y = 0; y < N; y++) {
        for (x = 0; x < N; x++) {
            size_t sx = x * L / N;
            size_t sy = y * L / N;
            size_t s = sy * L + sx;
            size_t d = y * N + x;
            memcpy(nn + d * 4, lo + s * 4, 4);
        }
    }
    sum = ta_artwork_rgb_sumsq(q8, nn, n_px);
    printf("artwork q8 vs nearest: sumsq=%llu\n", (unsigned long long)sum);
    CHECK(sum > 0);

    {
        uint8_t *calm = (uint8_t *)malloc(n_px * 4u);
        CHECK(calm != NULL);
        if (calm) {
            memcpy(calm, src, n_px * 4u);
            ta_artwork_calm_rgba(calm, N, N);
            CHECK(calm[0] != src[0] || calm[1] != src[1] || calm[2] != src[2]);
            free(calm);
        }
    }

    free(src);
    free(lo);
    free(q8);
    free(nn);
}

int main(void) {
    uint8_t rgba[4 * 4 * 4];
    size_t i;

    for (i = 0; i < 16; i++) {
        rgba[i * 4] = 255;
        rgba[i * 4 + 1] = 0;
        rgba[i * 4 + 2] = 0;
        rgba[i * 4 + 3] = 255;
    }
    ta_artwork_calm_rgba(rgba, 4, 4);
    CHECK(rgba[0] < 255);

    test_q8_vs_nearest();

    CHECK(ta_artwork_is_default(TA_ART_DEFAULT_FP) == 1);
    CHECK(ta_artwork_is_default(0x1234) == 0);
    CHECK(ta_artwork_path_looks_default("/albumart?path=default") == 1);
    CHECK(ta_artwork_path_looks_default("/albumart?web=Something") == 0);
    {
        uint8_t tiny[4] = {1, 2, 3, 255};
        uint32_t fp = ta_artwork_fingerprint_rgba(tiny, 1, 1);
        CHECK(fp != 0);
        CHECK(ta_artwork_fingerprint_rgba(tiny, 1, 1) == fp);
    }

    ta_registry_reset();
    ta_sched_reset();
    g_poll = g_upd = 0;
    ta_sched_start();
    CHECK(ta_registry_register(TA_NET_NAME, net_sink) == 0);
    CHECK(ta_registry_register(TA_DRAW_NAME, draw_sink) == 0);
    CHECK(ta_artwork_on_album_change(TA_NET_NAME, TA_DRAW_NAME, 3, 200) == 0);
    ta_sched_advance_ms(50);
    CHECK(g_poll == 1);
    ta_sched_advance_ms(150);
    CHECK(g_upd == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_artwork: %d checks ok\n", checks);
    return 0;
}
