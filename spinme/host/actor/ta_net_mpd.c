#include "ta_net_mpd.h"

#include "ta_net_backend.h"
#include "ta_registry.h"

#include <string.h>

void ta_net_mpd_reset(ta_net_mpd_t *m) {
    if (m != NULL) {
        memset(m, 0, sizeof(*m));
    }
}

static void remember_reply(ta_net_mpd_t *m, const char *reply_to,
                           ta_session_id_t session) {
    if (reply_to != NULL && reply_to[0] != '\0') {
        memcpy(m->reply_to, reply_to, TA_NAME_MAX);
    } else {
        m->reply_to[0] = '\0';
    }
    m->session_id = session;
}

static int complete_reply(ta_net_mpd_t *m, ta_event_type_t done) {
    ta_event_envelope_t reply;

    if (m->reply_to[0] == '\0') {
        return 0;
    }
    ta_env_clear(&reply);
    reply.event.type = done;
    reply.session_id = m->session_id;
    (void)ta_env_set_src(&reply, TA_NET_NAME);
    if (done == TA_EV_NET_POLL_DONE) {
        reply.event.u.coord_inform_playerstate.volume = TA_NET_STATUS_UNKNOWN;
        reply.event.u.coord_inform_playerstate.playing = TA_NET_STATUS_UNKNOWN;
    }
    return ta_registry_post(m->reply_to, &reply);
}

int ta_net_mpd_handle(ta_net_mpd_t *m, const ta_event_envelope_t *env) {
    if (m == NULL || env == NULL) {
        return -1;
    }
    switch (env->event.type) {
    case TA_EV_NET_SET_DIALECT:
        return 0;
    case TA_EV_NET_POLL:
        remember_reply(m, env->event.u.net_poll_playerstate.reply_to,
                       env->session_id);
        m->phase = TA_MPD_POLL_PENDING;
        m->polls++;
        return 0;
    case TA_EV_NET_SET:
        /* Coalesce volume: latest wins. Unsupported ops noop. */
        if (env->event.u.net_set.op == TA_NET_SET_OP_VOLUME ||
            env->event.u.net_set.op == TA_NET_SET_OP_TOGGLE) {
            m->volume = (int)env->event.u.net_set.volume;
            m->volume_dirty = 1;
            m->sets++;
        } else {
            m->noops++;
        }
        remember_reply(m, env->event.u.net_set.reply_to, env->session_id);
        return 0;
    case TA_EV_NET_ALBUMART:
        remember_reply(m, env->event.u.net_fetch_albumart.reply_to,
                       env->session_id);
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
