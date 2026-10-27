/* Full Core B script with a mock player and a virtual clock.
 *
 * A posts screen_on, pooled volume (rotate clicks), and press. B runs
 * the ring, the schedulers, and the zlist. The poll arm copies the next
 * scripted snapshot into polled volume and status. Toggle flips local
 * playing and records a command. There is no socket.
 *
 * integ_script_run also fills the ring and checks the drop. That section
 * logs two ERROR lines:
 *   event ring full, dropped volume
 *   event ring full, dropped update_render_draw
 *
 * The ping callback clears busy, standing in for Core A finishing redraw.
 */
#include "integ_script.h"

#include "uimk2_host.h"

#include <stdio.h>
#include <string.h>

static int g_checks;
static int g_failures;

#define CHECK(cond)                                                            \
    do {                                                                       \
        g_checks++;                                                            \
        if (!(cond)) {                                                         \
            g_failures++;                                                      \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,  \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

#define INTEG_CMD_MAX 8
#define INTEG_CMD_LEN 24
#define INTEG_STATUS_LEN 16

typedef struct {
    int volume;
    const char *status;
} integ_snap;

typedef struct {
    int volume;
    char status[INTEG_STATUS_LEN];
    int snaps_applied;
    int ncmd;
    char cmd[INTEG_CMD_MAX][INTEG_CMD_LEN];
} integ_player;

typedef struct {
    uimk2_host host;
    uimk2_ring ring;
    uimk2_zlist z;
    uint8_t curr[UIMK2_FRAME_BYTES];
    uint8_t next[UIMK2_FRAME_BYTES];
    integ_player player;
    const integ_snap *snaps;
    int nsnaps;
    uint32_t now;
    uint32_t urds;
    uint32_t screen_offs;
    int pings;
    int saw_clock_line;
    uint16_t title_i;
    uint16_t clock_i;
} integ_world;

static integ_world sim;

/* First poll is the old snapshot (desired is still moving). The press
 * poll and the later backoff polls report the player caught up. */
static const integ_snap MAIN_SNAP[] = {
    {40, "pause"}, {43, "play"}, {43, "play"}, {43, "play"},
    {43, "play"},  {43, "play"}, {43, "play"}, {43, "play"},
};

static const integ_snap TWO_SNAP[] = {
    {10, "pause"},
    {11, "play"},
};

static void on_ping(void *ctx) {
    integ_world *w = (integ_world *)ctx;
    w->pings++;
    w->z.busy = false;
    memset(w->z.row_dirty, 0, sizeof w->z.row_dirty);
}

static uimk2_event_sel sel_at(const uimk2_ring *r, uint32_t i) {
    return (uimk2_event_sel)r->slot[(r->head + i) % QUEUE_DEPTH].selector;
}

static int vol_at(const uimk2_ring *r, uint32_t i) {
    return r->slot[(r->head + i) % QUEUE_DEPTH].u.volume.new_val;
}

static int ring_has(const uimk2_ring *r, uimk2_event_sel sel) {
    uint32_t i;
    for (i = 0; i < r->len; i++) {
        if (sel_at(r, i) == sel) {
            return 1;
        }
    }
    return 0;
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

static void record_cmd(integ_player *p, const char *text) {
    if (p->ncmd >= INTEG_CMD_MAX) {
        return;
    }
    snprintf(p->cmd[p->ncmd], INTEG_CMD_LEN, "%s", text);
    p->ncmd++;
}

static void apply_snap(integ_player *p, const integ_snap *snaps, int n) {
    int i;
    const integ_snap *s;
    if (snaps == NULL || n <= 0) {
        return;
    }
    i = p->snaps_applied;
    if (i >= n) {
        i = n - 1;
    }
    s = &snaps[i];
    p->volume = s->volume;
    snprintf(p->status, sizeof p->status, "%s", s->status);
    p->snaps_applied++;
}

static int step_one(void) {
    uimk2_event *e;
    uint8_t sel;
    int vol;
    e = uimk2_ring_peek(&sim.ring);
    if (e == NULL) {
        return 0;
    }
    sel = e->selector;
    vol = (sel == (uint8_t)UIMK2_EV_VOLUME) ? e->u.volume.new_val : 0;
    if (!uimk2_host_step(&sim.host, sim.now)) {
        return 0;
    }
    if (sel == (uint8_t)UIMK2_EV_PLAYER_POLL) {
        apply_snap(&sim.player, sim.snaps, sim.nsnaps);
    } else if (sel == (uint8_t)UIMK2_EV_TOGGLE) {
        record_cmd(&sim.player, "toggle");
    } else if (sel == (uint8_t)UIMK2_EV_VOLUME) {
        char buf[INTEG_CMD_LEN];
        snprintf(buf, sizeof buf, "volume %d", vol);
        record_cmd(&sim.player, buf);
    } else if (sel == (uint8_t)UIMK2_EV_UPDATE_RENDER_DRAW) {
        sim.urds++;
        /* CLOCKTEXT is 24h HH:MM:SS from clock_tick (millis). */
        if (!sim.saw_clock_line && sim.host.clock_tick >= 1000u) {
            char want[16];
            uint32_t s = (sim.host.clock_tick / 1000u) % 86400u;
            snprintf(want, sizeof want, "%02u:%02u:%02u",
                     (unsigned)(s / 3600u), (unsigned)((s / 60u) % 60u),
                     (unsigned)(s % 60u));
            CHECK(strcmp(sim.z.shape[sim.clock_i].text, want) == 0);
            sim.saw_clock_line = 1;
        }
    } else if (sel == (uint8_t)UIMK2_EV_SCREEN_OFF) {
        sim.screen_offs++;
    }
    return 1;
}

static void pump(void) {
    while (step_one()) {
    }
}

static uimk2_shape_desc box(int x, int y, int w, int h, int hit, int transport) {
    uimk2_shape_desc d;
    memset(&d, 0, sizeof d);
    d.x = (int16_t)x;
    d.y = (int16_t)y;
    d.w = (uint16_t)w;
    d.h = (uint16_t)h;
    d.accept_hit = hit ? true : false;
    d.is_transport = transport ? true : false;
    d.rgba[0] = 20;
    d.rgba[1] = 30;
    d.rgba[2] = 40;
    d.rgba[3] = 255;
    return d;
}

static void build_scene(void) {
    uimk2_shape_desc d[4];
    memset(&sim, 0, sizeof sim);
    uimk2_ring_init(&sim.ring);
    uimk2_host_init(&sim.host, &sim.ring, 0);
    d[0] = box(100, 8, 160, 32, 1, 1);
    d[1] = box(16, 36, 300, 28, 0, 0);
    d[1].update_selector = (uint8_t)UIMK2_UPD_SCROLL;
    d[1].pw = 300; /* ox = (clock_tick/SCROLL_MS_PER_OX) % pw */
    d[1].ph = 28;
    d[2] = box(16, 300, 120, 20, 0, 0);
    d[2].update_selector = (uint8_t)UIMK2_UPD_CLOCKTEXT;
    d[3] = box(0, 0, (int)PANEL_W, (int)PANEL_H, 0, 0);
    d[3].is_base = true;
    d[3].rgba[0] = 8;
    d[3].rgba[1] = 8;
    d[3].rgba[2] = 12;
    sim.title_i = 1;
    sim.clock_i = 2;
    sim.snaps = MAIN_SNAP;
    sim.nsnaps = (int)(sizeof MAIN_SNAP / sizeof MAIN_SNAP[0]);
    CHECK(uimk2_zlist_build(&sim.z, d, 4, sim.curr, sim.next, &sim.ring, on_ping,
                            &sim));
    uimk2_host_bind(&sim.host, &sim.z);
}

static void wake_asserts(void) {
    CHECK(sim.host.backlight);
    CHECK(sim.host.poll_enabled);
    CHECK(sim.host.desired == 41);
    CHECK(!sim.host.playing);
    CHECK(sim.host.toggles == 0u);
    CHECK(sim.host.polls == 0u);
    CHECK(sim.host.renders == 1u);
    CHECK(sim.urds == 1u);
    CHECK(sim.pings == 1);
    /* First URD at now=0 => ox = (0/100) % 300. */
    CHECK(sim.z.shape[sim.title_i].ox == 0);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].last_run == 0u);
    CHECK(once_n(&sim.host) == 1u);
    CHECK(sim.host.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(sim.host.once[0].last_run == 0u);
    CHECK(sim.host.once[0].expire_by == SCREEN_OFF_EVERY);
    CHECK(sim.player.ncmd == 1);
    CHECK(strcmp(sim.player.cmd[0], "volume 41") == 0);
    CHECK(sim.player.snaps_applied == 0);
    CHECK(uimk2_ring_len(&sim.ring) == 0u);
    CHECK(sim.ring.dropped == 0u);
}

/* Poll is in the ring (possibly behind URD/CLOCK). Volumes sit behind it.
 * Then a transport press and a miss, still at this now. */
static void behind_poll_and_presses(void) {
    uint32_t off_last;
    uint32_t toggles;
    int guard = 0;
    CHECK(sim.now >= POLL_EVERY_START + 1u);
    CHECK(ring_has(&sim.ring, UIMK2_EV_PLAYER_POLL));
    while (sel_at(&sim.ring, 0) != UIMK2_EV_PLAYER_POLL) {
        CHECK(step_one());
        if (++guard > 32) {
            CHECK(0);
            return;
        }
    }
    CHECK(uimk2_post_volume(&sim.ring, 42));
    CHECK(uimk2_post_volume(&sim.ring, 43));
    CHECK(sel_at(&sim.ring, 0) == UIMK2_EV_PLAYER_POLL);
    CHECK(sel_at(&sim.ring, 1) == UIMK2_EV_VOLUME);
    CHECK(sel_at(&sim.ring, 2) == UIMK2_EV_VOLUME);
    CHECK(vol_at(&sim.ring, 1) == 42);
    CHECK(vol_at(&sim.ring, 2) == 43);

    off_last = sim.host.once[0].last_run;
    CHECK(step_one()); /* poll */
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START * 2u);
    CHECK(sim.host.once[0].last_run == off_last);
    CHECK(sim.host.once[0].expire_by == SCREEN_OFF_EVERY);
    CHECK(sim.host.desired == 41);
    CHECK(sim.player.volume == 40);
    CHECK(strcmp(sim.player.status, "pause") == 0);
    CHECK(!sim.host.playing);
    CHECK(step_one()); /* volume 42 */
    CHECK(sim.host.desired == 42);
    CHECK(sim.host.once[0].last_run == sim.now);
    CHECK(sim.host.once[0].expire_by == sim.now + SCREEN_OFF_EVERY);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    CHECK(step_one()); /* volume 43 */
    CHECK(sim.host.desired == 43);
    CHECK(sim.host.polls == 1u);
    CHECK(sim.player.snaps_applied == 1);
    CHECK(sim.player.ncmd == 3);
    CHECK(strcmp(sim.player.cmd[0], "volume 41") == 0);
    CHECK(strcmp(sim.player.cmd[1], "volume 42") == 0);
    CHECK(strcmp(sim.player.cmd[2], "volume 43") == 0);
    CHECK(uimk2_ring_len(&sim.ring) == 0u);

    CHECK(uimk2_post_press(&sim.ring, 110, 20));
    CHECK(step_one());
    CHECK(uimk2_ring_len(&sim.ring) == 2u);
    CHECK(sel_at(&sim.ring, 0) == UIMK2_EV_TOGGLE);
    CHECK(sel_at(&sim.ring, 1) == UIMK2_EV_PLAYER_POLL);
    CHECK(step_one());
    CHECK(sim.host.playing);
    CHECK(sim.host.toggles == 1u);
    CHECK(sim.player.volume == 40);
    CHECK(strcmp(sim.player.status, "pause") == 0);
    CHECK(strcmp(sim.player.cmd[3], "toggle") == 0);
    CHECK(step_one());
    CHECK(sim.host.polls == 2u);
    CHECK(sim.player.volume == 43);
    CHECK(strcmp(sim.player.status, "play") == 0);
    CHECK(sim.player.snaps_applied == 2);
    CHECK(uimk2_ring_len(&sim.ring) == 0u);

    toggles = sim.host.toggles;
    CHECK(uimk2_post_press(&sim.ring, 1, 1));
    CHECK(step_one());
    CHECK(sim.host.toggles == toggles);
    CHECK(sim.host.playing);
    CHECK(uimk2_ring_len(&sim.ring) == 0u);
    CHECK(!ring_has(&sim.ring, UIMK2_EV_TOGGLE));
    CHECK(sim.host.once[0].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF);
    CHECK(sim.host.once[0].last_run == sim.now);
    CHECK(sim.host.once[0].expire_by == sim.now + SCREEN_OFF_EVERY);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_START);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].last_run == sim.now);
    CHECK(sim.player.ncmd == 4);
}

static void sequence(void) {
    int guard = 0;
    int saw_poll = 0;
    int saw_off = 0;
    uint32_t polls;
    uint32_t later;

    build_scene();
    CHECK(uimk2_post_screen_on(&sim.ring));
    CHECK(uimk2_post_volume(&sim.ring, 41));
    pump();
    wake_asserts();

    while (!saw_off) {
        uint32_t delay;
        if (++guard > 10000) {
            CHECK(guard < 10000);
            break;
        }
        delay = uimk2_host_run(&sim.host, sim.now);
        CHECK(delay > 0u);
        if (!saw_poll && ring_has(&sim.ring, UIMK2_EV_PLAYER_POLL)) {
            behind_poll_and_presses();
            saw_poll = 1;
        } else {
            int was_on = sim.host.backlight ? 1 : 0;
            pump();
            if (was_on && !sim.host.backlight) {
                saw_off = 1;
                break;
            }
        }
        sim.now += delay;
    }

    CHECK(saw_poll);
    CHECK(saw_off);
    CHECK(sim.screen_offs == 1u);
    CHECK(!sim.host.backlight);
    CHECK(!sim.host.poll_enabled);
    CHECK(sim.host.playing);
    CHECK(sim.host.desired == 43);
    CHECK(sim.host.toggles == 1u);
    CHECK(sim.host.polls == 6u);
    CHECK(sim.player.snaps_applied == 6);
    CHECK(sim.player.volume == 43);
    CHECK(strcmp(sim.player.status, "play") == 0);
    CHECK(sim.player.ncmd == 4);
    CHECK(strcmp(sim.player.cmd[3], "toggle") == 0);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].every == POLL_EVERY_MAX);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_POLL].last_run == 16005u);
    CHECK(sim.now == 1001u + SCREEN_OFF_EVERY + 1u);
    CHECK(sim.urds > 1u);
    CHECK(sim.host.renders == sim.urds);
    CHECK(sim.z.shape[sim.title_i].ox ==
          (int16_t)((sim.host.clock_tick / SCROLL_MS_PER_OX) % 300u));
    CHECK(sim.saw_clock_line);
    CHECK(sim.host.clocks >= 2u);
    CHECK(sim.host.clock_sec ==
          (int32_t)(sim.host.clock_tick / CLOCKS_PER_SEC_TICKS));
    CHECK(sim.host.clock_tick >= 1000u);
    CHECK(once_n(&sim.host) == 0u);
    CHECK(sim.ring.dropped == 0u);
    CHECK(sim.pings == 1);
    CHECK(sim.z.redraw_attempt == 0);

    polls = sim.host.polls;
    later = sim.now + POLL_EVERY_MAX + 2u;
    sim.host.perm[UIMK2_HOST_PERM_CLOCK].last_run = later;
    sim.host.perm[UIMK2_HOST_PERM_RENDER].last_run = later;
    sim.host.perm[UIMK2_HOST_PERM_POLL].last_run = 0u;
    sim.host.perm[UIMK2_HOST_PERM_POLL].every = POLL_EVERY_START;
    uimk2_host_run(&sim.host, later);
    CHECK(!ring_has(&sim.ring, UIMK2_EV_PLAYER_POLL));
    CHECK(sim.host.polls == polls);
    CHECK(!sim.host.backlight);
    CHECK(!sim.host.poll_enabled);
    if (g_failures != 0) {
        fprintf(stderr,
                "integ sequence: now=%u polls=%u urds=%u ox=%d sec=%d "
                "tick=%u every=%u last_poll=%u snaps=%d ncmd=%d\n",
                sim.now, sim.host.polls, sim.urds,
                (int)sim.z.shape[sim.title_i].ox, (int)sim.host.clock_sec,
                sim.host.clock_tick, sim.host.perm[UIMK2_HOST_PERM_POLL].every,
                sim.host.perm[UIMK2_HOST_PERM_POLL].last_run,
                sim.player.snaps_applied, sim.player.ncmd);
    }
}

static void overflow(void) {
    uint32_t i;
    uimk2_ring_init(&sim.ring);
    uimk2_host_init(&sim.host, &sim.ring, 0);
    CHECK(uimk2_post_volume(&sim.ring, 42));
    CHECK(uimk2_post_volume(&sim.ring, 43));
    CHECK(uimk2_ring_len(&sim.ring) == 2u);
    CHECK(vol_at(&sim.ring, 0) == 42);
    CHECK(vol_at(&sim.ring, 1) == 43);
    for (i = 2; i < QUEUE_DEPTH; i++) {
        CHECK(uimk2_post_volume(&sim.ring, 50 + (int)i));
    }
    CHECK(uimk2_ring_len(&sim.ring) == QUEUE_DEPTH);
    CHECK(!uimk2_post_volume(&sim.ring, 999));
    CHECK(sim.ring.dropped == 1u);
    CHECK(uimk2_ring_len(&sim.ring) == QUEUE_DEPTH);
    CHECK(vol_at(&sim.ring, 0) == 42);
    CHECK(vol_at(&sim.ring, 1) == 43);
    for (i = 0; i < QUEUE_DEPTH; i++) {
        CHECK(sel_at(&sim.ring, i) == UIMK2_EV_VOLUME);
        CHECK(vol_at(&sim.ring, i) != 999);
    }

    sim.host.backlight = true;
    CHECK(uimk2_host_run(&sim.host, UPDATE_RENDER_EVERY + 1u) > 0u);
    CHECK(sim.host.perm[UIMK2_HOST_PERM_RENDER].last_run ==
          UPDATE_RENDER_EVERY + 1u);
    /* Full ring: refused URD and clock (same 200 ms cadence). */
    CHECK(sim.ring.dropped == 3u);
    CHECK(uimk2_ring_len(&sim.ring) == QUEUE_DEPTH);
    CHECK(!ring_has(&sim.ring, UIMK2_EV_UPDATE_RENDER_DRAW));
    CHECK(vol_at(&sim.ring, 0) == 42);
    CHECK(vol_at(&sim.ring, 1) == 43);

    uimk2_ring_init(&sim.ring);
    uimk2_host_init(&sim.host, &sim.ring, 0);
    memset(&sim.player, 0, sizeof sim.player);
    sim.snaps = TWO_SNAP;
    sim.nsnaps = (int)(sizeof TWO_SNAP / sizeof TWO_SNAP[0]);
    sim.now = 0;
    CHECK(uimk2_push_player_poll(&sim.ring));
    CHECK(uimk2_push_player_poll(&sim.ring));
    CHECK(uimk2_ring_len(&sim.ring) == 2u);
    CHECK(sel_at(&sim.ring, 0) == UIMK2_EV_PLAYER_POLL);
    CHECK(sel_at(&sim.ring, 1) == UIMK2_EV_PLAYER_POLL);
    CHECK(step_one());
    CHECK(sim.player.volume == 10);
    CHECK(strcmp(sim.player.status, "pause") == 0);
    CHECK(step_one());
    CHECK(sim.player.volume == 11);
    CHECK(strcmp(sim.player.status, "play") == 0);
    CHECK(sim.host.polls == 2u);
    CHECK(sim.player.snaps_applied == 2);
    CHECK(!sim.host.playing);
    CHECK(sim.host.toggles == 0u);
    CHECK(uimk2_ring_len(&sim.ring) == 0u);
}

static void finish(int *checks) {
    if (checks != NULL) {
        *checks = g_checks;
    }
}

int integ_sequence_run(int *checks) {
    g_checks = 0;
    g_failures = 0;
    sequence();
    finish(checks);
    return g_failures;
}

int integ_script_run(int *checks) {
    g_checks = 0;
    g_failures = 0;
    sequence();
    overflow();
    finish(checks);
    return g_failures;
}
