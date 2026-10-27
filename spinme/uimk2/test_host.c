/* Host tests for Core B schedulers and hit-test.
 *
 * Two expected ERROR lines on stderr:
 *   one-off list full, dropped redraw
 *   redraw busy at attempt cap 5
 */
#include "uimk2_host.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                        \
    do {                                                                   \
        checks++;                                                          \
        if (!(cond)) {                                                     \
            failures++;                                                    \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__,         \
                    __LINE__, #cond);                                      \
        }                                                                  \
    } while (0)

static uimk2_zlist z;
static uint8_t curr_mem[UIMK2_FRAME_BYTES];
static uint8_t next_mem[UIMK2_FRAME_BYTES];
static uint8_t base_mem[UIMK2_FRAME_BYTES];
static int pings;

static void on_ping(void *ctx) {
    int *n = ctx;
    (*n)++;
}

static void wipe_frames(void) {
    memset(curr_mem, 0, sizeof curr_mem);
    memset(next_mem, 0, sizeof next_mem);
    memset(base_mem, 0, sizeof base_mem);
    memset(&z, 0, sizeof z);
    pings = 0;
}

static uimk2_event_sel sel_at(const uimk2_ring *r, uint32_t i) {
    return (uimk2_event_sel)r->slot[(r->head + i) % QUEUE_DEPTH].selector;
}

static bool ring_has(const uimk2_ring *r, uimk2_event_sel sel) {
    uint32_t i;
    for (i = 0; i < r->len; i++) {
        if (sel_at(r, i) == sel) {
            return true;
        }
    }
    return false;
}

static uint32_t once_n(const uimk2_host *h) {
    uint32_t i;
    for (i = 0; i < UIMK2_HOST_ONCE; i++) {
        if (h->once[i].selector == (uint8_t)UIMK2_SCH_NONE) {
            return i;
        }
    }
    return UIMK2_HOST_ONCE;
}

static void drain(uimk2_host *h, uint32_t now) {
    while (uimk2_host_step(h, now)) {
    }
}

static uimk2_shape_desc box(int x, int y, int w, int h, bool hit,
                            bool transport) {
    uimk2_shape_desc d;
    memset(&d, 0, sizeof d);
    d.x = (int16_t)x;
    d.y = (int16_t)y;
    d.w = (uint16_t)w;
    d.h = (uint16_t)h;
    d.accept_hit = hit;
    d.is_transport = transport;
    d.rgba[0] = 1;
    d.rgba[1] = 2;
    d.rgba[2] = 3;
    d.rgba[3] = 255;
    return d;
}

static bool build(uimk2_host *h, uimk2_ring *r, const uimk2_shape_desc *d,
                  uint16_t n) {
    bool ok = uimk2_zlist_build(&z, d, n, curr_mem, next_mem, r, on_ping,
                                &pings);
    if (ok) {
        uimk2_host_bind(h, &z);
    }
    return ok;
}

/* A full ring still advances last_run before the refused push. */
static void test_last_run_before_push(void) {
    uimk2_host h;
    uimk2_ring r;
    uint32_t i;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    for (i = 0; i < QUEUE_DEPTH; i++) {
        CHECK(uimk2_post_volume(&r, (int)i));
    }
    /* Awake without screen_on's immediate update_render_draw. */
    h.backlight = true;
    CHECK(uimk2_host_run(&h, UPDATE_RENDER_EVERY) == 1u);
    CHECK(h.perm[UIMK2_HOST_PERM_RENDER].last_run == 0u);
    CHECK(r.dropped == 0u);
    CHECK(uimk2_host_run(&h, UPDATE_RENDER_EVERY + 1u) ==
          UPDATE_RENDER_EVERY + 1u);
    CHECK(h.perm[UIMK2_HOST_PERM_RENDER].last_run == UPDATE_RENDER_EVERY + 1u);
    /* Render and clock share the 200 ms cadence; both refuse on a full ring. */
    CHECK(r.dropped == 2u);
    CHECK(uimk2_ring_len(&r) == QUEUE_DEPTH);
    CHECK(sel_at(&r, 0) == UIMK2_EV_VOLUME);
    CHECK(!ring_has(&r, UIMK2_EV_UPDATE_RENDER_DRAW));
}

static void test_render_cadence(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_host_step(&h, 0));
    CHECK(h.backlight);
    CHECK(h.poll_enabled);
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(sel_at(&r, 0) == UIMK2_EV_UPDATE_RENDER_DRAW);
    CHECK(uimk2_host_run(&h, 0) == UPDATE_RENDER_EVERY + 1u);
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(uimk2_host_run(&h, UPDATE_RENDER_EVERY) == 1u);
    CHECK(h.perm[UIMK2_HOST_PERM_RENDER].last_run == 0u);
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(uimk2_host_run(&h, UPDATE_RENDER_EVERY + 1u) ==
          UPDATE_RENDER_EVERY + 1u);
    CHECK(h.perm[UIMK2_HOST_PERM_RENDER].last_run == UPDATE_RENDER_EVERY + 1u);
    /* Prior URD plus a new URD and a clock tick (same every). */
    CHECK(uimk2_ring_len(&r) == 3u);
    CHECK(sel_at(&r, 0) == UIMK2_EV_UPDATE_RENDER_DRAW);
    CHECK(ring_has(&r, UIMK2_EV_UPDATE_RENDER_DRAW));
    CHECK(ring_has(&r, UIMK2_EV_CLOCK));
    CHECK(!ring_has(&r, UIMK2_EV_PLAYER_POLL));
}

static void test_clock_while_asleep(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(once_n(&h) == 0u);
    CHECK(uimk2_host_run(&h, 0) == UIMK2_HOST_CLOCK_EVERY + 1u);
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(uimk2_host_run(&h, UIMK2_HOST_CLOCK_EVERY) == 1u);
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(uimk2_host_run(&h, UIMK2_HOST_CLOCK_EVERY + 1u) ==
          UIMK2_HOST_CLOCK_EVERY + 1u);
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(sel_at(&r, 0) == UIMK2_EV_CLOCK);
    CHECK(h.perm[UIMK2_HOST_PERM_CLOCK].last_run == UIMK2_HOST_CLOCK_EVERY + 1u);
    CHECK(!h.backlight);
    CHECK(uimk2_host_step(&h, UIMK2_HOST_CLOCK_EVERY + 1u));
    CHECK(h.clocks == 1u);
    CHECK(h.clock_sec ==
          (int32_t)((UIMK2_HOST_CLOCK_EVERY + 1u) / CLOCKS_PER_SEC_TICKS));
    CHECK(h.clock_tick == UIMK2_HOST_CLOCK_EVERY + 1u);
}

static void test_poll_backoff(void) {
    uimk2_host h;
    uimk2_ring r;
    uint32_t gap = POLL_EVERY_START;
    int fires;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_host_step(&h, 0));
    drain(&h, 0);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    for (fires = 0; fires < 5; fires++) {
        uint32_t last = h.perm[UIMK2_HOST_PERM_POLL].last_run;
        uint32_t now = last + gap + 1u;
        uint32_t before = h.polls;
        uimk2_ring_init(&r);
        uimk2_host_run(&h, now);
        drain(&h, now);
        CHECK(h.polls == before + 1u);
        gap *= 2u;
        if (gap > POLL_EVERY_MAX) {
            gap = POLL_EVERY_MAX;
        }
        CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == gap);
        CHECK(h.perm[UIMK2_HOST_PERM_POLL].last_run == now);
    }
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_MAX);
}

static void test_screen_off_and_poll_stop(void) {
    uimk2_host h;
    uimk2_ring r;
    uint32_t t;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_host_step(&h, 0));
    CHECK(uimk2_host_step(&h, 0)); /* wake update_render_draw */
    CHECK(once_n(&h) == 1u);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(h.once[0].every == SCREEN_OFF_EVERY);
    CHECK(h.once[0].expire_by == SCREEN_OFF_EVERY);
    CHECK(h.once[0].last_run == 0u);
    CHECK(h.once[1].selector == (uint8_t)UIMK2_SCH_NONE);
    /* A poll result does not arm screen-off again. */
    CHECK(uimk2_push_player_poll(&r));
    CHECK(uimk2_host_step(&h, 0));
    CHECK(h.polls == 1u);
    CHECK(h.once[0].last_run == 0u);
    CHECK(h.once[0].expire_by == SCREEN_OFF_EVERY);

    uimk2_ring_init(&r);
    CHECK(uimk2_host_run(&h, SCREEN_OFF_EVERY) >= 1u);
    CHECK(!ring_has(&r, UIMK2_EV_SCREEN_OFF));
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    uimk2_ring_init(&r);
    uimk2_host_run(&h, SCREEN_OFF_EVERY + 1u);
    CHECK(ring_has(&r, UIMK2_EV_SCREEN_OFF));
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_NONE);
    CHECK(h.once[0].every == 0u);
    drain(&h, SCREEN_OFF_EVERY + 1u);
    CHECK(!h.backlight);
    CHECK(!h.poll_enabled);

    t = SCREEN_OFF_EVERY + 1u + POLL_EVERY_START + 1u;
    h.perm[UIMK2_HOST_PERM_CLOCK].last_run = t;
    h.perm[UIMK2_HOST_PERM_RENDER].last_run = t;
    h.perm[UIMK2_HOST_PERM_POLL].last_run = 0u;
    h.perm[UIMK2_HOST_PERM_POLL].every = POLL_EVERY_START;
    uimk2_ring_init(&r);
    uimk2_host_run(&h, t);
    CHECK(uimk2_ring_len(&r) == 0u);
}

static void test_one_off_pack_and_expire(void) {
    uimk2_host h;
    uimk2_ring r;
    uint32_t i;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(uimk2_host_arm_once(&h, (uint8_t)UIMK2_SCH_REDRAW, 0, 50u, 50u, 3));
    CHECK(uimk2_host_arm_once(&h, (uint8_t)UIMK2_SCH_SCREEN_OFF, 0, 30000u,
                              30000u, 0));
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_REDRAW);
    CHECK(h.once[0].attempt == 3);
    CHECK(h.once[1].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(h.once[2].selector == (uint8_t)UIMK2_SCH_NONE);
    CHECK(uimk2_host_run(&h, 50) == 1u);
    CHECK(uimk2_ring_len(&r) == 0u);
    uimk2_host_run(&h, 51);
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(sel_at(&r, 0) == UIMK2_EV_REDRAW);
    CHECK(uimk2_ring_peek(&r)->u.redraw.attempt == 3);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(h.once[0].last_run == 0u);
    CHECK(h.once[1].selector == (uint8_t)UIMK2_SCH_NONE);
    CHECK(h.once[1].every == 0u);
    CHECK(h.once[1].attempt == 0);

    /* every and expire_by differ: fire until now has passed expire_by. */
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(uimk2_host_arm_once(&h, (uint8_t)UIMK2_SCH_SCREEN_OFF, 0, 10u, 25u,
                              0));
    CHECK(uimk2_host_run(&h, 10) == 1u);
    CHECK(uimk2_ring_len(&r) == 0u);
    uimk2_host_run(&h, 11);
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(h.once[0].last_run == 11u);
    uimk2_host_run(&h, 22);
    CHECK(uimk2_ring_len(&r) == 2u);
    CHECK(h.once[0].last_run == 22u);
    uimk2_host_run(&h, 33);
    CHECK(uimk2_ring_len(&r) == 3u);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_NONE);
    for (i = 0; i < 3u; i++) {
        CHECK(sel_at(&r, i) == UIMK2_EV_SCREEN_OFF);
    }

    /* expire_by already past, and not due: drop with no push. */
    uimk2_ring_init(&r);
    CHECK(uimk2_host_arm_once(&h, (uint8_t)UIMK2_SCH_REDRAW, 100u, 1000u, 50u,
                              1));
    uimk2_host_run(&h, 100);
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(once_n(&h) == 0u);

    uimk2_host_init(&h, &r, 0);
    for (i = 0; i < UIMK2_HOST_ONCE; i++) {
        CHECK(uimk2_host_arm_once(&h, (uint8_t)UIMK2_SCH_REDRAW, 0, 50u, 50u,
                                  (int)i));
    }
    CHECK(once_n(&h) == UIMK2_HOST_ONCE);
    CHECK(h.once[UIMK2_HOST_ONCE].selector == (uint8_t)UIMK2_SCH_NONE);
    CHECK(!uimk2_host_arm_once(&h, (uint8_t)UIMK2_SCH_REDRAW, 0, 50u, 50u, 9));
    CHECK(h.once[UIMK2_HOST_ONCE - 1u].attempt == (int)UIMK2_HOST_ONCE - 1);
}

static void test_redraw_retry(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_shape_desc d;
    uint32_t now;
    const uimk2_event *ev;
    int expect;

    wipe_frames();
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    d = box(0, 0, (int)PANEL_W, (int)PANEL_H, false, false);
    d.is_base = true;
    CHECK(build(&h, &r, &d, 1));
    z.busy = true;
    CHECK(uimk2_push_update_render_draw(&r));
    CHECK(uimk2_host_step(&h, 0));
    CHECK(h.renders == 1u);
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(!z.redraw_held);
    CHECK(z.redraw_attempt == 1);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_REDRAW);
    CHECK(h.once[0].attempt == 1);
    CHECK(h.once[0].every == REDRAW_RETRY_EVERY);
    CHECK(h.once[0].expire_by == REDRAW_RETRY_EVERY);
    CHECK(h.once[0].last_run == 0u);
    CHECK(h.once[1].selector == (uint8_t)UIMK2_SCH_NONE);
    CHECK(uimk2_host_run(&h, REDRAW_RETRY_EVERY) == 1u);
    CHECK(uimk2_ring_len(&r) == 0u);
    now = REDRAW_RETRY_EVERY + 1u;
    uimk2_host_run(&h, now);
    ev = uimk2_ring_peek(&r);
    CHECK(ev != NULL);
    CHECK(ev->selector == (uint8_t)UIMK2_EV_REDRAW);
    CHECK(ev->u.redraw.attempt == 1);
    CHECK(once_n(&h) == 0u);

    z.busy = false;
    CHECK(uimk2_host_step(&h, now));
    CHECK(pings == 1);
    CHECK(z.busy);
    CHECK(z.curr == next_mem);
    CHECK(once_n(&h) == 0u);
    CHECK(h.last_attempt == 1);
    CHECK(uimk2_ring_len(&r) == 0u);

    /* Stay busy. Arming attempt == CAP logs ERROR once. */
    wipe_frames();
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    d = box(0, 0, (int)PANEL_W, (int)PANEL_H, false, false);
    d.is_base = true;
    CHECK(build(&h, &r, &d, 1));
    z.busy = true;
    CHECK(uimk2_push_update_render_draw(&r));
    CHECK(uimk2_host_step(&h, 0));
    for (expect = 1; expect < (int)REDRAW_ATTEMPT_CAP; expect++) {
        uint32_t last = h.once[0].last_run;
        uint32_t due = last + h.once[0].every + 1u;
        /* Keep permanent clock/render from also pushing on this due. */
        h.perm[UIMK2_HOST_PERM_CLOCK].last_run = due;
        h.perm[UIMK2_HOST_PERM_RENDER].last_run = due;
        h.perm[UIMK2_HOST_PERM_POLL].last_run = due;
        uimk2_ring_init(&r);
        uimk2_host_run(&h, due - 1u);
        CHECK(uimk2_ring_len(&r) == 0u);
        uimk2_host_run(&h, due);
        ev = uimk2_ring_peek(&r);
        CHECK(ev != NULL);
        CHECK(ev->selector == (uint8_t)UIMK2_EV_REDRAW);
        CHECK(ev->u.redraw.attempt == expect);
        CHECK(uimk2_host_step(&h, due));
        CHECK(h.once[0].attempt == expect + 1);
        CHECK(uimk2_ring_len(&r) == 0u);
    }
    CHECK(h.once[0].attempt == (int)REDRAW_ATTEMPT_CAP);
    CHECK(z.redraw_attempt == (int)REDRAW_ATTEMPT_CAP);
    CHECK(z.busy);
    CHECK(pings == 0);
    CHECK(z.curr == curr_mem);
}

static void test_hit(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_shape_desc d[3];
    static uint8_t dot[2 * 2 * 4];
    uint32_t off;

    wipe_frames();
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    d[0] = box(0, 0, 20, 20, true, false);
    d[1] = box(0, 0, 20, 20, true, false);
    d[2] = box(40, 40, 8, 8, true, false);
    CHECK(build(&h, &r, d, 3));
    CHECK(uimk2_zlist_hit_test(&z, 0, 0) == 0);
    CHECK(uimk2_zlist_hit_test(&z, 19, 19) == 0);
    CHECK(uimk2_zlist_hit_test(&z, 20, 0) == -1);
    CHECK(uimk2_zlist_hit_test(&z, -1, 0) == -1);
    CHECK(uimk2_zlist_hit_test(&z, 40, 40) == 2);
    CHECK(uimk2_zlist_hit_test(&z, 100, 100) == -1);
    CHECK(uimk2_zlist_hit_test(NULL, 0, 0) == -1);

    d[0] = box(0, 0, 20, 20, false, false);
    d[1] = box(0, 0, 20, 20, true, true);
    CHECK(build(&h, &r, d, 2));
    CHECK(uimk2_zlist_hit_test(&z, 1, 1) == 1);

    CHECK(build(&h, &r, NULL, 0));
    CHECK(uimk2_zlist_hit_test(&z, 0, 0) == -1);

    CHECK(HIT_OPAQUE_PCT == 0u);
    d[0] = box(0, 0, 8, 8, true, false);
    d[0].rgba[3] = 0;
    CHECK(build(&h, &r, d, 1));
    CHECK(uimk2_zlist_hit_test(&z, 1, 1) == 0);
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 50u) == -1);
    z.shape[0].rgba[3] = 127;
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 50u) == -1);
    z.shape[0].rgba[3] = 128;
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 50u) == 0);
    z.shape[0].rgba[3] = 254;
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 100u) == -1);
    z.shape[0].rgba[3] = 255;
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 100u) == 0);

    memset(dot, 0, sizeof dot);
    dot[3] = 10;
    dot[7] = 255;
    d[0] = box(10, 20, 2, 2, true, false);
    d[0].px = dot;
    d[1] = box(10, 20, 2, 2, true, false);
    CHECK(build(&h, &r, d, 2));
    CHECK(uimk2_zlist_hit_test(&z, 10, 20) == 0);
    CHECK(uimk2_zlist_hit_test_pct(&z, 10, 20, 50u) == 1);
    CHECK(uimk2_zlist_hit_test_pct(&z, 11, 20, 50u) == 0);

    d[0] = box(0, 0, 4, 4, true, false);
    d[0].is_base = true;
    d[0].px = base_mem;
    CHECK(build(&h, &r, d, 1));
    off = (1u * PANEL_W + 1u) * 4u + 3u;
    base_mem[off] = 20;
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 50u) == -1);
    base_mem[off] = 255;
    CHECK(uimk2_zlist_hit_test_pct(&z, 1, 1, 50u) == 0);
}

static void test_press_transport(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_shape_desc d[2];

    wipe_frames();
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    d[0] = box(100, 8, 160, 32, true, true);
    d[1] = box(0, 0, 10, 10, true, false);
    CHECK(build(&h, &r, d, 2));

    /* Asleep: Toggle, and arm poll, with no immediate Poll. */
    CHECK(uimk2_post_press(&r, 110, 10));
    CHECK(uimk2_host_step(&h, 5));
    CHECK(uimk2_ring_len(&r) == 1u);
    CHECK(sel_at(&r, 0) == UIMK2_EV_TOGGLE);
    CHECK(!h.playing);
    CHECK(h.poll_enabled);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].last_run == 5u);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(h.once[0].last_run == 5u);
    CHECK(h.once[0].expire_by == 5u + SCREEN_OFF_EVERY);
    CHECK(uimk2_host_step(&h, 5));
    CHECK(h.playing);
    CHECK(h.toggles == 1u);
    CHECK(uimk2_ring_len(&r) == 0u);

    /* A miss still rearms screen-off and does not enqueue Toggle. */
    CHECK(uimk2_post_press(&r, 1, 1));
    CHECK(uimk2_host_step(&h, 80));
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(h.toggles == 1u);
    CHECK(h.once[0].last_run == 80u);
    CHECK(once_n(&h) == 1u);

    /* Awake: transport enqueues Toggle and Poll. */
    uimk2_host_bind(&h, NULL);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_host_step(&h, 80));
    CHECK(uimk2_host_step(&h, 80));
    CHECK(h.backlight);
    uimk2_host_bind(&h, &z);
    CHECK(uimk2_post_press(&r, 120, 12));
    CHECK(uimk2_host_step(&h, 90));
    CHECK(uimk2_ring_len(&r) == 2u);
    CHECK(sel_at(&r, 0) == UIMK2_EV_TOGGLE);
    CHECK(sel_at(&r, 1) == UIMK2_EV_PLAYER_POLL);
    CHECK(h.once[0].last_run == 90u);
    drain(&h, 90);
    CHECK(!h.playing);
    CHECK(h.toggles == 2u);
    CHECK(h.polls == 1u);

    /* A closer accept_hit shape hides the transport under it. */
    d[0] = box(100, 8, 160, 32, true, false);
    d[1] = box(100, 8, 160, 32, true, true);
    CHECK(build(&h, &r, d, 2));
    CHECK(uimk2_zlist_hit_test(&z, 110, 10) == 0);
    CHECK(uimk2_post_press(&r, 110, 10));
    CHECK(uimk2_host_step(&h, 100));
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(h.toggles == 2u);

    /* A closer shape that does not accept hits does not hide it. */
    d[0] = box(100, 8, 160, 32, false, false);
    d[1] = box(100, 8, 160, 32, true, true);
    CHECK(build(&h, &r, d, 2));
    CHECK(uimk2_zlist_hit_test(&z, 110, 10) == 1);
    CHECK(uimk2_post_press(&r, 110, 10));
    CHECK(uimk2_host_step(&h, 110));
    CHECK(sel_at(&r, 0) == UIMK2_EV_TOGGLE);
    CHECK(ring_has(&r, UIMK2_EV_PLAYER_POLL));
}

/* B stores desired. Later volume values do not replace earlier ones. */
static void test_desired_volume(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(h.desired == 0);
    CHECK(!h.poll_enabled);
    CHECK(uimk2_post_volume(&r, 41));
    CHECK(uimk2_host_step(&h, 10));
    CHECK(h.desired == 41);
    CHECK(h.poll_enabled);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].last_run == 10u);
    CHECK(h.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(uimk2_post_volume(&r, 42));
    CHECK(uimk2_post_volume(&r, 43));
    CHECK(uimk2_ring_len(&r) == 2u);
    CHECK(uimk2_ring_peek(&r)->u.volume.new_val == 42);
    CHECK(uimk2_host_step(&h, 11));
    CHECK(h.desired == 42);
    CHECK(uimk2_ring_peek(&r)->u.volume.new_val == 43);
    CHECK(uimk2_host_step(&h, 12));
    CHECK(h.desired == 43);
    CHECK(uimk2_ring_len(&r) == 0u);
    CHECK(!h.playing);
}

static void test_volume_resets_poll_gap(void) {
    uimk2_host h;
    uimk2_ring r;
    uint32_t now;
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_host_step(&h, 0));
    drain(&h, 0);
    now = POLL_EVERY_START + 1u;
    uimk2_ring_init(&r);
    uimk2_host_run(&h, now);
    drain(&h, now);
    CHECK(h.polls == 1u);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START * 2u);
    CHECK(uimk2_post_volume(&r, 7));
    CHECK(uimk2_host_step(&h, now));
    CHECK(h.desired == 7);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    CHECK(h.perm[UIMK2_HOST_PERM_POLL].last_run == now);
    CHECK(h.once[0].last_run == now);
}

static void test_clock_reaches_zlist(void) {
    uimk2_host h;
    uimk2_ring r;
    uimk2_shape_desc d;
    wipe_frames();
    uimk2_ring_init(&r);
    uimk2_host_init(&h, &r, 0);
    d = box(0, 0, 1, 1, false, false);
    CHECK(build(&h, &r, &d, 1));
    uimk2_host_run(&h, UIMK2_HOST_CLOCK_EVERY + 1u);
    CHECK(uimk2_host_step(&h, UIMK2_HOST_CLOCK_EVERY + 1u));
    CHECK(z.clock_sec ==
          (int32_t)((UIMK2_HOST_CLOCK_EVERY + 1u) / CLOCKS_PER_SEC_TICKS));
    CHECK(z.clock_tick == UIMK2_HOST_CLOCK_EVERY + 1u);
}

int main(void) {
    test_last_run_before_push();
    test_render_cadence();
    test_clock_while_asleep();
    test_poll_backoff();
    test_screen_off_and_poll_stop();
    test_one_off_pack_and_expire();
    test_redraw_retry();
    test_hit();
    test_press_transport();
    test_desired_volume();
    test_volume_resets_poll_gap();
    test_clock_reaches_zlist();
    printf("test_host: %d checks, %d failures\n", checks, failures);
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
