/* Host: Net dialect/poll/albumart stubs; reply_to completions. */
#include "ta_event.h"
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

static ta_event_t g_reply;
static int g_n;

static int mpd_sink(const ta_event_t *ev) {
    g_reply = *ev;
    g_n++;
    return 0;
}

int main(void) {
    ta_event_t ev;
    const ta_net_stats_t *st;

    ta_registry_reset();
    ta_net_reset();
    g_n = 0;
    ta_net_start();
    CHECK(ta_registry_register("MPDController", mpd_sink) == 0);

    ta_event_clear(&ev);
    ev.type = TA_EV_NET_SET_DIALECT;
    ev.session_id = 1;
    CHECK(ta_event_set_src(&ev, "Config") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &ev) == 0);

    ta_event_clear(&ev);
    ev.type = TA_EV_NET_POLL;
    ev.session_id = 42;
    CHECK(ta_event_set_src(&ev, "MPDController") == 0);
    CHECK(ta_event_set_reply(&ev, "MPDController", TA_EV_NET_POLL_DONE) == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &ev) == 0);
    CHECK(g_n == 1);
    CHECK(g_reply.type == TA_EV_NET_POLL_DONE);
    CHECK(g_reply.session_id == 42);

    ta_event_clear(&ev);
    ev.type = TA_EV_NET_ALBUMART;
    ev.session_id = 42;
    CHECK(ta_event_set_src(&ev, "MPDController") == 0);
    CHECK(ta_event_set_reply(&ev, "MPDController", TA_EV_NET_ALBUMART_DONE) ==
          0);
    CHECK(ta_registry_post(TA_NET_NAME, &ev) == 0);
    CHECK(g_n == 2);
    CHECK(g_reply.type == TA_EV_NET_ALBUMART_DONE);

    ta_event_clear(&ev);
    ev.type = TA_EV_NET_SET;
    CHECK(ta_event_set_src(&ev, "MPDController") == 0);
    CHECK(ta_registry_post(TA_NET_NAME, &ev) == 0);

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

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_net_events: %d checks ok\n", checks);
    return 0;
}
