#include "ta_net_events.h"

#include "ta_net_backend.h"
#include "ta_registry.h"

#include <string.h>

static ta_net_stats_t g_stats;
static const ta_net_backend_t *g_backend;

/* Pending completion targets (one in flight per class for now). */
static char g_poll_reply[TA_NAME_MAX];
static ta_session_id_t g_poll_session;
static char g_set_reply[TA_NAME_MAX];
static ta_session_id_t g_set_session;
static char g_art_reply[TA_NAME_MAX];
static ta_session_id_t g_art_session;

void ta_net_reset(void) {
    memset(&g_stats, 0, sizeof(g_stats));
    g_backend = NULL;
    g_poll_reply[0] = '\0';
    g_set_reply[0] = '\0';
    g_art_reply[0] = '\0';
}

void ta_net_set_backend(const ta_net_backend_t *backend) {
    g_backend = backend;
}

const ta_net_stats_t *ta_net_stats(void) {
    return &g_stats;
}

static void remember(char *dst, ta_session_id_t *sess, const char *reply_to,
                     ta_session_id_t session) {
    if (reply_to != NULL && reply_to[0] != '\0') {
        memcpy(dst, reply_to, TA_NAME_MAX);
    } else {
        dst[0] = '\0';
    }
    *sess = session;
}

static void post_done(const char *reply_to, ta_session_id_t session,
                      ta_event_type_t done_type,
                      const ta_coord_inform_playerstate_t *status) {
    ta_event_envelope_t reply;

    if (reply_to == NULL || reply_to[0] == '\0') {
        return;
    }
    ta_env_clear(&reply);
    reply.event.type = done_type;
    reply.session_id = session;
    (void)ta_env_set_src(&reply, TA_NET_NAME);
    if (done_type == TA_EV_NET_POLL_DONE) {
        if (status != NULL) {
            reply.event.u.coord_inform_playerstate = *status;
        } else {
            /* No snapshot: leave volume/playing unknown (0xFF), not 0. */
            reply.event.u.coord_inform_playerstate.volume =
                TA_NET_STATUS_UNKNOWN;
            reply.event.u.coord_inform_playerstate.playing =
                TA_NET_STATUS_UNKNOWN;
        }
    }
    if (ta_registry_post(reply_to, &reply) == 0) {
        g_stats.replies_posted++;
    }
}

static void maybe_reply_immediate(const char *reply_to, ta_session_id_t session,
                                  ta_event_type_t done) {
    post_done(reply_to, session, done, NULL);
}

/* Take the pending slot, clear it, then post: the DONE handler may issue a
 * new request of the same class synchronously (MPD coalesced volume), and
 * that new reply_to must survive this completion. */
static void complete_slot(char *reply, ta_session_id_t *session,
                          ta_event_type_t done_type,
                          const ta_coord_inform_playerstate_t *status) {
    char to[TA_NAME_MAX];
    ta_session_id_t sess = *session;

    memcpy(to, reply, TA_NAME_MAX);
    reply[0] = '\0';
    post_done(to, sess, done_type, status);
}

void ta_net_backend_complete_ex(int kind, const uint8_t *payload, size_t len) {
    ta_coord_inform_playerstate_t status;
    const ta_coord_inform_playerstate_t *st = NULL;

    memset(&status, 0, sizeof(status));
    if (payload != NULL && len >= TA_NET_STATUS_LEN) {
        status.volume = payload[TA_NET_STATUS_VOLUME];
        status.playing = payload[TA_NET_STATUS_PLAYING];
        st = &status;
    }
    switch (kind) {
    case 1: /* poll ok */
    case 2: /* poll fail -- still DONE so Controllers unblock */
        complete_slot(g_poll_reply, &g_poll_session, TA_EV_NET_POLL_DONE, st);
        break;
    case 3:
    case 4:
        complete_slot(g_set_reply, &g_set_session, TA_EV_NET_SET_DONE, NULL);
        break;
    case 5:
    case 6:
        complete_slot(g_art_reply, &g_art_session, TA_EV_NET_ALBUMART_DONE,
                      NULL);
        break;
    default:
        break;
    }
}

void ta_net_backend_complete(int kind) {
    ta_net_backend_complete_ex(kind, NULL, 0);
}

int ta_net_handle(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    switch (env->event.type) {
    case TA_EV_NET_SET_DIALECT:
        g_stats.set_dialect++;
        g_stats.handled++;
        return 0;
    case TA_EV_NET_POLL:
        g_stats.poll++;
        g_stats.handled++;
        if (g_backend == NULL || g_backend->request_poll == NULL) {
            maybe_reply_immediate(env->event.u.net_poll_playerstate.reply_to,
                                  env->session_id, TA_EV_NET_POLL_DONE);
            return 0;
        }
        remember(g_poll_reply, &g_poll_session,
                 env->event.u.net_poll_playerstate.reply_to, env->session_id);
        if (g_backend->request_poll() != 0) {
            complete_slot(g_poll_reply, &g_poll_session, TA_EV_NET_POLL_DONE,
                          NULL);
        }
        return 0;
    case TA_EV_NET_SET:
        g_stats.set++;
        g_stats.handled++;
        if (g_backend == NULL) {
            maybe_reply_immediate(env->event.u.net_set.reply_to, env->session_id,
                                  TA_EV_NET_SET_DONE);
            return 0;
        }
        remember(g_set_reply, &g_set_session, env->event.u.net_set.reply_to,
                 env->session_id);
        {
            int rc = -1;
            uint8_t op = env->event.u.net_set.op;

            if (op == TA_NET_SET_OP_TOGGLE) {
                if (g_backend->request_toggle != NULL) {
                    rc = g_backend->request_toggle();
                }
            } else if (g_backend->request_volume != NULL) {
                rc = g_backend->request_volume((int)env->event.u.net_set.volume);
            }
            if (rc != 0) {
                complete_slot(g_set_reply, &g_set_session, TA_EV_NET_SET_DONE,
                              NULL);
            }
        }
        return 0;
    case TA_EV_NET_ALBUMART:
        g_stats.albumart++;
        g_stats.handled++;
        if (g_backend == NULL || g_backend->request_albumart == NULL) {
            maybe_reply_immediate(env->event.u.net_fetch_albumart.reply_to,
                                  env->session_id, TA_EV_NET_ALBUMART_DONE);
            return 0;
        }
        remember(g_art_reply, &g_art_session,
                 env->event.u.net_fetch_albumart.reply_to, env->session_id);
        if (g_backend->request_albumart(env->event.u.net_fetch_albumart.path,
                                        512u * 1024u) != 0) {
            complete_slot(g_art_reply, &g_art_session, TA_EV_NET_ALBUMART_DONE,
                          NULL);
        }
        return 0;
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_net_enqueue(const ta_event_envelope_t *env) {
    return ta_net_handle(env);
}

void ta_net_start(void) {
    (void)ta_registry_register(TA_NET_NAME, ta_net_enqueue);
}
