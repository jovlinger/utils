/* Host integration: Router -> MPDController -> Net (fake deferred backend),
 * Scheduler-driven poll cadence, reply_to / session_id round trips. */
#include "ta_controller.h"
#include "ta_draw_events.h"
#include "ta_event.h"
#include "ta_net_backend.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_router.h"
#include "ta_sched_events.h"

#include <stdio.h>
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

/* Fake wire: count requests, complete only when the test says so. */
static int g_be_poll;
static int g_be_toggle;
static int g_be_vol;
static int g_be_vol_last;
static int g_be_reject; /* when set, requests return -1 (not configured) */

static int be_poll(void) {
    g_be_poll++;
    return g_be_reject ? -1 : 0;
}

static int be_toggle(void) {
    g_be_toggle++;
    return g_be_reject ? -1 : 0;
}

static int be_volume(int volume) {
    g_be_vol++;
    g_be_vol_last = volume;
    return g_be_reject ? -1 : 0;
}

static const ta_net_backend_t g_fake_be = {be_poll, be_toggle, be_volume, NULL};

/* Originator sink (what Draw/Config would see as the controller's echo). */
static ta_event_envelope_t g_org_last;
static int g_org_n;

static int origin_sink(const ta_event_envelope_t *env) {
    g_org_last = *env;
    g_org_n++;
    return 0;
}

static int post_ctrl(ta_event_type_t type, ta_session_id_t session,
                     uint8_t vol_mode, int8_t delta, ta_volume_t absolute,
                     int want_reply) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.event.type = type;
    env.session_id = session;
    (void)ta_env_set_src(&env, TA_DRAW_NAME);
    if (type == TA_EV_CTRL_TOGGLE) {
        if (want_reply) {
            (void)ta_copy_name(env.event.u.ctrl_toggle.reply_to, TA_NAME_MAX,
                               "Origin");
        }
    } else if (type == TA_EV_CTRL_VOLUME) {
        env.event.u.ctrl_volume.mode = vol_mode;
        env.event.u.ctrl_volume.delta = delta;
        env.event.u.ctrl_volume.absolute = absolute;
        if (want_reply) {
            (void)ta_copy_name(env.event.u.ctrl_volume.reply_to, TA_NAME_MAX,
                               "Origin");
        }
    } else if (type == TA_EV_CTRL_SET_ACTIVE && want_reply) {
        (void)ta_copy_name(env.event.u.ctrl_set_active.reply_to, TA_NAME_MAX,
                           "Origin");
    }
    return ta_registry_post(TA_CONTROLLER_NAME, &env);
}

static int post_set_route(const char *target) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.event.type = TA_EV_SET_ROUTE;
    (void)ta_env_set_src(&env, "Config");
    (void)ta_event_set_ctrl_set_route(&env.event, target);
    return ta_registry_post(TA_CONTROLLER_NAME, &env);
}

static void boot(void) {
    ta_registry_reset();
    ta_router_reset();
    ta_mpd_reset();
    ta_sonos_reset();
    ta_draw_reset();
    ta_net_reset();
    ta_sched_reset();
    g_be_poll = g_be_toggle = g_be_vol = 0;
    g_be_vol_last = -1;
    g_be_reject = 0;
    g_org_n = 0;

    ta_router_start();
    ta_mpd_start();
    ta_sonos_start();
    ta_draw_start();
    ta_net_start();
    ta_sched_start();
    ta_net_set_backend(&g_fake_be);
    CHECK(ta_registry_register("Origin", origin_sink) == 0);
}

static void test_poll_cadence(void) {
    const ta_controller_stats_t *st = ta_mpd_stats();

    boot();
    CHECK(post_set_route(TA_MPD_NAME) == 0);
    CHECK(post_ctrl(TA_EV_CTRL_SET_ACTIVE, 5, 0, 0, 0, 0) == 0);
    CHECK(ta_sched_stats()->starts == 1);
    CHECK(ta_net_stats()->set_dialect == 1);
    CHECK(g_be_poll == 0);

    /* Scheduler fires CTRL_POLL at TA_MPD_POLL_MS; MPD posts NET_POLL. */
    ta_sched_advance_ms(TA_MPD_POLL_MS - 1);
    CHECK(g_be_poll == 0);
    ta_sched_advance_ms(1);
    CHECK(g_be_poll == 1);
    CHECK(st->net_poll_posted == 1);
    CHECK(ta_mpd_poll_inflight() == 1);

    /* Wire slow: next tick must not stack a second poll. */
    ta_sched_advance_ms(TA_MPD_POLL_MS);
    CHECK(g_be_poll == 1);
    CHECK(st->polls_skipped == 1);

    ta_net_backend_complete(1); /* POLL_DONE -> MPD (reply_to honored) */
    CHECK(st->poll_done == 1);
    CHECK(ta_mpd_poll_inflight() == 0);

    ta_sched_advance_ms(TA_MPD_POLL_MS);
    CHECK(g_be_poll == 2);
    ta_net_backend_complete(2); /* poll fail still completes */
    CHECK(st->poll_done == 2);
    CHECK(ta_mpd_poll_inflight() == 0);
}

static void test_toggle_and_volume(void) {
    const ta_controller_stats_t *st = ta_mpd_stats();

    boot();
    CHECK(post_set_route(TA_MPD_NAME) == 0);
    CHECK(post_ctrl(TA_EV_CTRL_SET_ACTIVE, 5, 0, 0, 0, 0) == 0);

    /* Toggle: NET_SET [TOGGLE]; origin echo waits for SET_DONE. */
    CHECK(post_ctrl(TA_EV_CTRL_TOGGLE, 88, 0, 0, 0, 1) == 0);
    CHECK(g_be_toggle == 1);
    CHECK(st->net_set_posted == 1);
    CHECK(ta_mpd_set_inflight() == 1);
    CHECK(g_org_n == 0);

    /* Rotary +3 while SET in flight: model moves, Net waits. */
    CHECK(post_ctrl(TA_EV_CTRL_VOLUME, 89, TA_CTRL_VOL_REL, 3, 0, 1) == 0);
    CHECK(ta_mpd_volume() == TA_MPD_VOL_DEFAULT + 3);
    CHECK(g_be_vol == 0);
    CHECK(st->coalesced == 1);

    /* Another +2 before the wire settles: still one deferred SET. */
    CHECK(post_ctrl(TA_EV_CTRL_VOLUME, 90, TA_CTRL_VOL_REL, 2, 0, 1) == 0);
    CHECK(ta_mpd_volume() == TA_MPD_VOL_DEFAULT + 5);
    CHECK(st->coalesced == 2);

    ta_net_backend_complete(3); /* toggle cmd ok */
    CHECK(st->set_done == 1);
    CHECK(g_org_n == 1);
    CHECK(g_org_last.event.type == TA_EV_CTRL_TOGGLE);
    CHECK(g_org_last.session_id == 88);
    CHECK(strcmp(g_org_last.src, TA_MPD_NAME) == 0);
    /* Deferred volume flushed with the final model value. */
    CHECK(g_be_vol == 1);
    CHECK(g_be_vol_last == TA_MPD_VOL_DEFAULT + 5);
    CHECK(ta_mpd_set_inflight() == 1);

    ta_net_backend_complete(3); /* volume cmd ok */
    CHECK(st->set_done == 2);
    CHECK(g_org_n == 2);
    CHECK(g_org_last.event.type == TA_EV_CTRL_VOLUME);
    CHECK(g_org_last.session_id == 90); /* latest coalesced originator */
    CHECK(ta_mpd_set_inflight() == 0);
    /* Settled -> status refresh poll. */
    CHECK(g_be_poll == 1);
    CHECK(ta_mpd_poll_inflight() == 1);
    ta_net_backend_complete(1);

    /* Absolute volume. */
    CHECK(post_ctrl(TA_EV_CTRL_VOLUME, 91, TA_CTRL_VOL_ABS, 0, 20, 0) == 0);
    CHECK(ta_mpd_volume() == 20);
    CHECK(g_be_vol == 2);
    CHECK(g_be_vol_last == 20);
    ta_net_backend_complete(3);
    CHECK(g_org_n == 2); /* no reply_to: no echo */
    ta_net_backend_complete(1);

    /* Touch on volume chrome (NONE): no Net traffic, echo only. */
    CHECK(post_ctrl(TA_EV_CTRL_VOLUME, 92, TA_CTRL_VOL_NONE, 0, 0, 1) == 0);
    CHECK(g_be_vol == 2);
    CHECK(g_org_n == 3);
    CHECK(g_org_last.session_id == 92);

    /* Clamp. */
    CHECK(post_ctrl(TA_EV_CTRL_VOLUME, 93, TA_CTRL_VOL_REL, (int8_t)-100, 0,
                    0) == 0);
    CHECK(ta_mpd_volume() == 0);
    ta_net_backend_complete(3);
    ta_net_backend_complete(1);

    /* Net never saw a direct controller call: all through registry. */
    CHECK(ta_net_stats()->set == st->net_set_posted);
    CHECK(ta_net_stats()->poll == st->net_poll_posted);
}

static void test_rejected_wire(void) {
    const ta_controller_stats_t *st = ta_mpd_stats();

    boot();
    g_be_reject = 1; /* e.g. Wi-Fi not configured: Net completes at once */
    CHECK(post_set_route(TA_MPD_NAME) == 0);
    CHECK(post_ctrl(TA_EV_CTRL_SET_ACTIVE, 5, 0, 0, 0, 0) == 0);
    CHECK(post_ctrl(TA_EV_CTRL_TOGGLE, 1, 0, 0, 0, 1) == 0);
    CHECK(g_be_toggle == 1);
    CHECK(st->set_done == 1);
    CHECK(ta_mpd_set_inflight() == 0);
    CHECK(g_org_n == 1); /* originator unblocked even on failure */
    CHECK(ta_mpd_poll_inflight() == 0);
    ta_sched_advance_ms(TA_MPD_POLL_MS);
    CHECK(st->polls_skipped == 0);
    CHECK(ta_mpd_poll_inflight() == 0);
}

static void test_route_to_sonos(void) {
    boot();
    CHECK(post_set_route(TA_SONOS_NAME) == 0);
    CHECK(post_ctrl(TA_EV_CTRL_TOGGLE, 1, 0, 0, 0, 1) == 0);
    CHECK(ta_sonos_stats()->toggle == 1);
    CHECK(ta_mpd_stats()->toggle == 0);
    CHECK(g_be_toggle == 0); /* Sonos stub posts nothing to Net */
    CHECK(g_org_n == 1);
}

int main(void) {
    test_poll_cadence();
    test_toggle_and_volume();
    test_rejected_wire();
    test_route_to_sonos();

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_mpd_net: %d checks ok\n", checks);
    return 0;
}
