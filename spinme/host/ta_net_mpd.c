#include "ta_net_mpd.h"

#include "ta_registry.h"

#include <string.h>

void ta_net_mpd_reset(ta_net_mpd_t *m) {
    if (m != NULL) {
        memset(m, 0, sizeof(*m));
    }
}

static void remember_reply(ta_net_mpd_t *m, const ta_event_t *ev) {
    if (ev->reply_to[0] != '\0') {
        memcpy(m->reply_to, ev->reply_to, TA_NAME_MAX);
        m->reply_type = ev->reply_type;
    } else {
        m->reply_to[0] = '\0';
    }
    m->session_id = ev->session_id;
}

static int complete_reply(ta_net_mpd_t *m, ta_event_type_t done) {
    ta_event_t reply;

    if (m->reply_to[0] == '\0') {
        return 0;
    }
    ta_event_clear(&reply);
    reply.type = done;
    reply.session_id = m->session_id;
    (void)ta_event_set_src(&reply, TA_NET_NAME);
    return ta_registry_post(m->reply_to, &reply);
}

int ta_net_mpd_handle(ta_net_mpd_t *m, const ta_event_t *ev) {
    if (m == NULL || ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_NET_SET_DIALECT:
        return 0;
    case TA_EV_NET_POLL:
        remember_reply(m, ev);
        m->phase = TA_MPD_POLL_PENDING;
        m->polls++;
        return 0;
    case TA_EV_NET_SET:
        /* Coalesce volume: latest wins. Unsupported ops noop. */
        if (ev->payload_len >= 1) {
            m->volume = (int)ev->payload[0];
            m->volume_dirty = 1;
            m->sets++;
        } else {
            m->noops++;
        }
        remember_reply(m, ev);
        return 0;
    case TA_EV_NET_ALBUMART:
        remember_reply(m, ev);
        m->phase = TA_MPD_ALBUMART_PENDING;
        m->albumarts++;
        return 0;
    case TA_EV_CTRL_NEXT:
    case TA_EV_CTRL_PREV:
        /* Unsupported on stub dialect -> noop. */
        m->noops++;
        return 0;
    default:
        m->noops++;
        return 0;
    }
}

int ta_net_mpd_tick(ta_net_mpd_t *m) {
    if (m == NULL) {
        return -1;
    }
    if (m->volume_dirty) {
        m->volume_dirty = 0;
        /* Simulated wire send of coalesced volume. */
    }
    if (m->phase == TA_MPD_POLL_PENDING) {
        m->phase = TA_MPD_IDLE;
        return complete_reply(m, TA_EV_NET_POLL_DONE);
    }
    if (m->phase == TA_MPD_ALBUMART_PENDING) {
        m->phase = TA_MPD_IDLE;
        return complete_reply(m, TA_EV_NET_ALBUMART_DONE);
    }
    return 0;
}
