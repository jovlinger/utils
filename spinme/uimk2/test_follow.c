/* Host follow view: fixed volume slot, album/title rewind, desired overlay. */
#include "uimk2_follow.h"

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
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,  \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

#define CAP 160
#define SW 240
#define SH 200

static uimk2_bm storage[CAP];
static uint32_t arena_buf[1 << 16];
static uint8_t screen[SW * SH * 4];

static int px_eq(const uint8_t *p, int r, int g, int b, int a) {
    return p[0] == r && p[1] == g && p[2] == b && p[3] == a;
}

/* Straight-alpha, desired in front, after the cache's alpha scale of 128. */
static void blend_front(const uint8_t fg[4], const uint8_t bg[4], uint8_t out[4]) {
    uint32_t fa = ((uint32_t)fg[3] * 128u + 127u) / 255u;
    uint32_t under = ((255u - fa) * bg[3] + 127u) / 255u;
    uint32_t a = fa + under;
    int c;
    if (a == 0) {
        memset(out, 0, 4);
        return;
    }
    for (c = 0; c < 3; c++) {
        uint32_t cp = fa * fg[c] + under * bg[c];
        out[c] = (uint8_t)((cp + a / 2u) / a);
    }
    out[3] = (uint8_t)a;
}

static void test_follow(void) {
    uimk2_follow f;
    uimk2_sched sched;
    uint8_t artist_px[4096];
    uint32_t artist_off, artist_bytes, top_same, activity;
    uint16_t artist_cache;
    int x, y, found;
    int bx, bw;

    CHECK(uimk2_follow_init(&f, storage, CAP, arena_buf, sizeof arena_buf,
                            screen, SW, SH));
    CHECK(f.volume.arena_off < f.arena.static_top);
    CHECK(f.zone.arena_off < f.arena.static_top);
    CHECK(f.button_w > f.bm.bm[f.play.cache].w);
    CHECK(f.button_w > f.bm.bm[f.stop.cache].w);

    CHECK(uimk2_follow_set_text(&f, "Ab", "Cd", "Ef"));
    CHECK(f.artist.arena_off == f.arena.album_mark);
    CHECK(f.title.arena_off == f.arena.song_mark);
    uimk2_follow_repaint(&f);
    artist_off = f.artist.arena_off;
    artist_cache = f.artist.cache;
    artist_bytes = (uint32_t)f.bm.bm[artist_cache].w * f.bm.bm[artist_cache].h * 4u;
    CHECK(artist_bytes <= sizeof artist_px);
    memcpy(artist_px, f.bm.bm[artist_cache].u.cache.px, artist_bytes);

    top_same = f.arena.top;
    CHECK(uimk2_follow_set_text(&f, "Ab", "Cd", "Ef"));
    CHECK(f.arena.top == top_same);
    CHECK(f.artist.arena_off == artist_off);

    CHECK(uimk2_follow_set_text(&f, "Ab", "Cd", "Zz"));
    CHECK(f.artist.cache == artist_cache);
    CHECK(f.artist.arena_off == artist_off);
    CHECK(memcmp(f.bm.bm[artist_cache].u.cache.px, artist_px, artist_bytes) == 0);
    CHECK(f.title.arena_off == f.arena.song_mark);
    CHECK(strcmp(f.title_s, "Zz") == 0);

    CHECK(uimk2_follow_set_text(&f, "Qw", "Cd", "Zz"));
    CHECK(f.artist.arena_off == f.arena.album_mark);
    CHECK(f.title.arena_off == f.arena.song_mark);
    CHECK(strcmp(f.artist_s, "Qw") == 0);

    bx = f.button_x;
    bw = f.button_w;
    uimk2_follow_set_status(&f, "play");
    CHECK(f.showing_stop);
    CHECK(f.button_x == bx && f.button_w == bw);
    uimk2_follow_set_status(&f, "pause");
    CHECK(!f.showing_stop);
    CHECK(f.button_x == bx && f.button_w == bw);

    uimk2_follow_set_volume(&f, 10);
    CHECK(f.overlay);
    CHECK(f.vol == 10);
    uimk2_follow_repaint(&f);
    found = 0;
    for (y = 0; y < f.bm.bm[f.desired.cache].h && !found; y++) {
        for (x = 0; x < f.bm.bm[f.desired.cache].w; x++) {
            const uint8_t *fg =
                &f.bm.bm[f.desired.cache]
                     .u.cache.px[(y * f.bm.bm[f.desired.cache].w + x) * 4];
            const uint8_t *bg =
                &f.bm.bm[f.volume.cache]
                     .u.cache.px[(y * f.bm.bm[f.volume.cache].w + x) * 4];
            uint8_t expect[4];
            const uint8_t *sp;
            if (fg[3] != 255 || x >= f.bm.bm[f.volume.cache].w) {
                continue;
            }
            blend_front(fg, bg, expect);
            sp = &screen[((f.volume_y + y) * SW + (f.volume_x + x)) * 4];
            found = px_eq(sp, expect[0], expect[1], expect[2], expect[3]);
            CHECK(found);
            break;
        }
    }
    CHECK(found);

    uimk2_sched_init(&sched);
    uimk2_follow_set_sched(&f, &sched);
    activity = sched.last_activity;
    CHECK(uimk2_follow_snapshot(&f, "Qw", "Cd", "Zz", 10));
    CHECK(sched.last_activity == activity);
    CHECK(sched.ui_len == 1 && sched.ui[0].kind == UIMK2_UI_SNAPSHOT);

    CHECK(uimk2_follow_knob(&f, 1, 50));
    CHECK(f.desired_vol == 1);
    CHECK(sched.last_activity == 50);
    CHECK(sched.work_len == 1 && sched.work[0].kind == UIMK2_WORK_SET_VOLUME);
    CHECK(sched.work[0].volume == 1);

    CHECK(!uimk2_follow_touch(&f, 0, 0, 80));
    CHECK(uimk2_follow_touch(&f, f.button_x + 1, f.button_y + 1, 80));
    CHECK(sched.last_activity == 80);
    CHECK(sched.work_len == 2 && sched.work[1].kind == UIMK2_WORK_TOGGLE);
}

int main(void) {
    test_follow();
    printf("test_follow: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
