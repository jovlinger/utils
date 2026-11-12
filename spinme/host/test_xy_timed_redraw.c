/* Timed XY redraw model: under digits, semi veil, over letters across t. */
#include "ta_uilayout.h"

#include <stdio.h>
#include <string.h>

enum {
    GLASS_W = 32,
    GLASS_H = 16,
    TIMES = 10, /* t = 0..9 => digits 0..9 and letters a..j */
    Z_UNDER = 5,
    Z_VEIL = 3,
    Z_OVER = 1,
    UNDER_X = 2,
    UNDER_Y = 2,
    VEIL_X = 0,
    VEIL_Y = 0,
    VEIL_W = 20,
    VEIL_H = 12,
    CELL = 2
};

/*
 * Caller wrote veil as 0x08080801 meaning channels R=G=B=0x08, a2=1
 * (RGBA byte order). pack66 memory order is R|G<<8|B<<16|A<<24 => 0x01080808.
 */
#define VEIL_PX ta_pack66_rgba(0x08, 0x08, 0x08, 1)

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

/* Src-over a2 into resolved glass (same rule as ta_draw_phase1). */
static ta_pack66_t blend_a2(ta_pack66_t dst, ta_pack66_t src) {
    uint8_t sr, sg, sb, sa;
    uint8_t dr, dg, db, da;
    unsigned inv;

    ta_unpack66(src, &sr, &sg, &sb, &sa);
    if (sa == 0) {
        return dst;
    }
    if (sa >= 3) {
        return src;
    }
    ta_unpack66(dst, &dr, &dg, &db, &da);
    (void)da;
    inv = 3u - (unsigned)sa;
    return ta_pack66_rgba(
        (uint8_t)(((unsigned)sr * sa + (unsigned)dr * inv) / 3u),
        (uint8_t)(((unsigned)sg * sa + (unsigned)dg * inv) / 3u),
        (uint8_t)(((unsigned)sb * sa + (unsigned)db * inv) / 3u), 3);
}

static void glass_clear(ta_pack66_t *g) {
    memset(g, 0, (size_t)GLASS_W * (size_t)GLASS_H * sizeof(*g));
}

static void blit_px(ta_pack66_t *dst, int ox, int oy, int w, int h,
                    ta_pack66_t px) {
    int y;
    int x;

    for (y = 0; y < h; y++) {
        int dy = oy + y;
        if (dy < 0 || dy >= GLASS_H) {
            continue;
        }
        for (x = 0; x < w; x++) {
            int dx = ox + x;
            size_t di;
            uint8_t a;

            if (dx < 0 || dx >= GLASS_W) {
                continue;
            }
            di = (size_t)dy * GLASS_W + (size_t)dx;
            a = (uint8_t)((px >> TA_PACK66_A2_SHIFT) & 3u);
            if (a == 0) {
                continue;
            }
            if (a >= 3) {
                dst[di] = px;
            } else {
                dst[di] = blend_a2(dst[di], px);
            }
        }
    }
}

/* Opaque ink unique per digit 0..9 (z=5 under). */
static ta_pack66_t digit_ink(int d) {
    uint8_t v = (uint8_t)(8u + (unsigned)d * 5u); /* 8..53 in 6-bit range */
    return ta_pack66_rgba(v, 4, 4, 3);
}

/* Opaque ink unique per letter a..j (z=1 over). */
static ta_pack66_t letter_ink(int t) {
    uint8_t v = (uint8_t)(8u + (unsigned)t * 5u);
    return ta_pack66_rgba(4, v, 4, 3);
}

static void over_xy(int t, int *x, int *y) {
    /* Distinct XY per time so over moves across the veil. */
    *x = 4 + t * 2;
    *y = 4 + (t % 3);
}

/*
 * Explicit XYShape-style glass write: only this path reaches glass.
 * Painter order high-z (under) -> veil -> low-z (over).
 */
static void xy_redraw(ta_pack66_t *glass, int t) {
    int ox;
    int oy;

    glass_clear(glass);
    /* z=5 under: digit 0..9 at fixed XY */
    blit_px(glass, UNDER_X, UNDER_Y, CELL, CELL, digit_ink(t));
    /* z=3 veil: semi-transparent sheet (channels 8,8,8 a2=1) */
    blit_px(glass, VEIL_X, VEIL_Y, VEIL_W, VEIL_H, VEIL_PX);
    /* z=1 over: letter a..j at time-varying XY */
    over_xy(t, &ox, &oy);
    blit_px(glass, ox, oy, CELL, CELL, letter_ink(t));
    (void)Z_UNDER;
    (void)Z_VEIL;
    (void)Z_OVER;
}

static ta_pack66_t expect_through_veil(int t) {
    /* opaque under, then veil a2=1 src-over */
    return blend_a2(digit_ink(t), VEIL_PX);
}

static int sample(const ta_pack66_t *g, int x, int y) {
    return (int)g[(size_t)y * GLASS_W + (size_t)x];
}

int main(void) {
    ta_pack66_t glass[GLASS_W * GLASS_H];
    ta_pack66_t prev_through;
    int t;

    CHECK(VEIL_PX == 0x01080808u);

    prev_through = 0;
    for (t = 0; t < TIMES; t++) {
        int ox;
        int oy;
        ta_pack66_t through;
        ta_pack66_t at_over;
        int ux = UNDER_X;
        int uy = UNDER_Y;

        xy_redraw(glass, t);
        over_xy(t, &ox, &oy);

        through = expect_through_veil(t);
        /* Under cell, not covered by over: must show digit through veil. */
        if (!(ox == ux && oy == uy)) {
            CHECK((ta_pack66_t)sample(glass, ux, uy) == through);
            CHECK((ta_pack66_t)sample(glass, ux + 1, uy + 1) == through);
        }

        /* Over cell (on top of veil): opaque letter wins. */
        at_over = letter_ink(t);
        CHECK((ta_pack66_t)sample(glass, ox, oy) == at_over);
        CHECK((ta_pack66_t)sample(glass, ox + 1, oy + 1) == at_over);

        /* Outside veil and outside glyphs: still clear. */
        CHECK(sample(glass, GLASS_W - 1, GLASS_H - 1) == 0);

        /* Time advance changes under-through-veil when over does not cover. */
        if (t > 0 && !(ox == ux && oy == uy)) {
            CHECK(through != prev_through);
        }
        prev_through = through;
    }

    /* Spot-check two times differ on glass under the veil. */
    {
        ta_pack66_t a[GLASS_W * GLASS_H];
        ta_pack66_t b[GLASS_W * GLASS_H];
        xy_redraw(a, 0);
        xy_redraw(b, 9);
        CHECK(sample(a, UNDER_X, UNDER_Y) != sample(b, UNDER_X, UNDER_Y));
        CHECK(sample(a, 4, 4) != sample(b, 4 + 9 * 2, 4 + (9 % 3)));
    }

    if (failures) {
        fprintf(stderr, "test_xy_timed_redraw: %d/%d failed\n", failures,
                checks);
        return 1;
    }
    printf("test_xy_timed_redraw: %d checks ok\n", checks);
    return 0;
}
