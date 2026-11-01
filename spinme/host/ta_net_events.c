#include "ta_net_events.h"

#include "ta_registry.h"

#include <string.h>

static ta_net_stats_t g_stats;

void ta_net_reset(void) {
    memset(&g_stats, 0, sizeof(g_stats));
}

const ta_net_stats_t *ta_net_stats(void) {
    return &g_stats;
}

static void maybe_reply(const ta_event_t *ev, ta_event_type_t done_type) {
    ta_event_t reply;

    if (ev->reply_to[0] == '\0') {
        return;
    }
    ta_event_clear(&reply);
    reply.type = done_type;
    reply.session_id = ev->session_id;
    (void)ta_event_set_src(&reply, TA_NET_NAME);
    if (ta_registry_post(ev->reply_to, &reply) == 0) {
        g_stats.replies_posted++;
    }
}

int ta_net_handle(const ta_event_t *ev) {
    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_NET_SET_DIALECT:
        g_stats.set_dialect++;
        g_stats.handled++;
        return 0;
    case TA_EV_NET_POLL:
        g_stats.poll++;
        g_stats.handled++;
        maybe_reply(ev, TA_EV_NET_POLL_DONE);
        return 0;
    case TA_EV_NET_SET:
        g_stats.set++;
        g_stats.handled++;
        maybe_reply(ev, TA_EV_NET_SET_DONE);
        return 0;
    case TA_EV_NET_ALBUMART:
        g_stats.albumart++;
        g_stats.handled++;
        maybe_reply(ev, TA_EV_NET_ALBUMART_DONE);
        return 0;
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_net_enqueue(const ta_event_t *ev) {
    return ta_net_handle(ev);
}

void ta_net_start(void) {
    (void)ta_registry_register(TA_NET_NAME, ta_net_enqueue);
}
