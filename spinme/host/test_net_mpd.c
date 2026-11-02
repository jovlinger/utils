/* Host: MPD dialect poll/set coalesce + albumart reply_to. */
#include "ta_event.h"
#include "ta_net_backend.h"
#include "ta_net_mpd.h"
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

static ta_event_envelope_t g_last;
static int g_n;

static int sink(const ta_event_envelope_t *env) {
    g_last = *env;
    g_n++;
    return 0;
}

int main(void) {
    ta_net_mpd_t mpd;
    ta_event_envelope_t env;

    ta_registry_reset();
    ta_net_mpd_reset(&mpd);
    g_n = 0;
    CHECK(ta_registry_register("MPDController", sink) == 0);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_SET;
    (void)ta_event_set_net_set(&env.event, NULL, (uint8_t)TA_NET_SET_OP_VOLUME,
                               10);
    CHECK(ta_net_mpd_handle(&mpd, &env) == 0);
    (void)ta_event_set_net_set(&env.event, NULL, (uint8_t)TA_NET_SET_OP_VOLUME,
                               42);
    CHECK(ta_net_mpd_handle(&mpd, &env) == 0);
    CHECK(mpd.volume == 42);
    CHECK(mpd.sets == 2);
    CHECK(ta_net_mpd_tick(&mpd) == 0);
    CHECK(mpd.volume_dirty == 0);

    ta_env_clear(&env);
    env.event.type = TA_EV_CTRL_NEXT;
    CHECK(ta_net_mpd_handle(&mpd, &env) == 0);
    CHECK(mpd.noops == 1);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_POLL;
    env.session_id = 7;
    CHECK(ta_event_set_net_poll_playerstate(&env.event, "MPDController") == 0);
    CHECK(ta_net_mpd_handle(&mpd, &env) == 0);
    CHECK(ta_net_mpd_tick(&mpd) == 0);
    CHECK(g_n == 1);
    CHECK(g_last.event.type == TA_EV_NET_POLL_DONE);
    CHECK(g_last.session_id == 7);

    ta_env_clear(&env);
    env.event.type = TA_EV_NET_ALBUMART;
    env.session_id = 8;
    CHECK(ta_copy_name(env.event.u.net_fetch_albumart.reply_to, TA_NAME_MAX,
                       "MPDController") == 0);
    CHECK(ta_net_mpd_handle(&mpd, &env) == 0);
    CHECK(ta_net_mpd_tick(&mpd) == 0);
    CHECK(g_n == 2);
    CHECK(g_last.event.type == TA_EV_NET_ALBUMART_DONE);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_net_mpd: %d checks ok\n", checks);
    return 0;
}
