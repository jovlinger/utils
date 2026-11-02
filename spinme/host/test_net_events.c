/* Host: Net dialect/poll/albumart; reply_to; fake backend seam. */
#include "ta_event.h"
#include "ta_net_backend.h"
#include "ta_net_events.h"
#include "ta_registry.h"

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

static ta_event_envelope_t g_reply;
static int g_n;
static int g_be_poll;
static int g_be_toggle;
static int g_be_vol;
static int g_be_vol_last;

static int mpd_sink(const ta_event_envelope_t *env) {
    g_reply = *env;
    g_n++;
    return 0;
}

static int be_poll(void) {
    g_be_poll++;
    return 0;
}

static int be_toggle(void) {
    g_be_toggle++;
    return 0;
}

static int be_volume(int volume) {
    g_be_vol++;
    g_be_vol_last = volume;
    return 0;
}

static const ta_net_backend_t g_fake_be = {be_poll, be_toggle, be_volume, NULL};

int main(void) {
    ta_event_envelope_t env;
    const ta_net_stats_t *st;

    ta_registry_reset();
    ta_net_reset();
    g_n = 0;
    ta_net_start();
    CHECK(ta_registry_register("MPDController", mpd_sink) == 0);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_SET_DIALECT;
    env.session_id = 1;
    CHECK(ta_env_set_src(&env, "Config") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_POLL;
    env.session_id = 42;
    CHECK(ta_env_set_src(&env, "MPDController") == 0);
    CHECK(ta_event_set_net_poll_playerstate(&env.event, "MPDController") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);
    CHECK(g_n == 1);
    CHECK(g_reply.event.type == TA_EV_NET_POLL_DONE);
    CHECK(g_reply.session_id == 42);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_ALBUMART;
    env.session_id = 42;
    CHECK(ta_env_set_src(&env, "MPDController") == 0);
    CHECK(ta_copy_name(env.event.u.net_fetch_albumart.reply_to, TA_NAME_MAX,
                       "MPDController") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);
    CHECK(g_n == 2);
    CHECK(g_reply.event.type == TA_EV_NET_ALBUMART_DONE);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_SET;
    CHECK(ta_env_set_src(&env, "MPDController") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);

    st = ta_net_stats();
    CHECK(st->handled == 4);
    CHECK(st->set_dialect == 1);
    CHECK(st->poll == 1);
    CHECK(st->albumart == 1);
    CHECK(st->set == 1);
    CHECK(st->replies_posted == 2);

    /* ControlEvents enum is declared for Controllers (compile check). */
    CHECK(TA_EV_CTRL_TOGGLE == 0x400);
    CHECK(TA_EV_CTRL_SET_ACTIVE == 0x404);

    /* Fake backend: queue ops, complete later via ta_net_backend_complete. */
    ta_net_reset();
    ta_net_start();
    g_n = 0;
    g_be_poll = g_be_toggle = g_be_vol = 0;
    ta_net_set_backend(&g_fake_be);
    CHECK(ta_registry_register("MPDController", mpd_sink) == 0);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_POLL;
    env.session_id = 7;
    CHECK(ta_event_set_net_poll_playerstate(&env.event, "MPDController") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);
    CHECK(g_be_poll == 1);
    CHECK(g_n == 0); /* deferred until complete */
    ta_net_backend_complete(1);
    CHECK(g_n == 1);
    CHECK(g_reply.event.type == TA_EV_NET_POLL_DONE);
    CHECK(g_reply.session_id == 7);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_SET;
    CHECK(ta_event_set_net_set(&env.event, "MPDController",
                               (uint8_t)TA_NET_SET_OP_TOGGLE, 0) == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);
    CHECK(g_be_toggle == 1);
    ta_net_backend_complete(3);
    CHECK(g_reply.event.type == TA_EV_NET_SET_DONE);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_SET;
    CHECK(ta_event_set_net_set(&env.event, NULL, (uint8_t)TA_NET_SET_OP_VOLUME,
                               44) == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &env) == 0);
    CHECK(g_be_vol == 1);
    CHECK(g_be_vol_last == 44);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_net_events: %d checks ok\n", checks);
    return 0;
}
