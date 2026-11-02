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

static void remember(char *dst, ta_session_id_t *sess, const ta_event_t *ev) {
    if (ev->reply_to[0] != '\0') {
        memcpy(dst, ev->reply_to, TA_NAME_MAX);
    } else {
        dst[0] = '\0';
    }
    *sess = ev->session_id;
}

static void post_done(const char *reply_to, ta_session_id_t session,
                      ta_event_type_t done_type) {
    ta_event_t reply;

    if (reply_to == NULL || reply_to[0] == '\0') {
        return;
    }
    ta_event_clear(&reply);
    reply.type = done_type;
    reply.session_id = session;
    (void)ta_event_set_src(&reply, TA_NET_NAME);
    if (ta_registry_post(reply_to, &reply) == 0) {
        g_stats.replies_posted++;
    }
}

static void maybe_reply_immediate(const ta_event_t *ev, ta_event_type_t done) {
    post_done(ev->reply_to, ev->session_id, done);
}

void ta_net_backend_complete(int kind) {
    switch (kind) {
    case 1: /* poll ok */
    case 2: /* poll fail -- still DONE so Controllers unblock */
        post_done(g_poll_reply, g_poll_session, TA_EV_NET_POLL_DONE);
        g_poll_reply[0] = '\0';
        break;
    case 3:
    case 4:
        post_done(g_set_reply, g_set_session, TA_EV_NET_SET_DONE);
        g_set_reply[0] = '\0';
        break;
    case 5:
    case 6:
        post_done(g_art_reply, g_art_session, TA_EV_NET_ALBUMART_DONE);
        g_art_reply[0] = '\0';
        break;
    default:
        break;
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
        if (g_backend == NULL || g_backend->request_poll == NULL) {
            maybe_reply_immediate(ev, TA_EV_NET_POLL_DONE);
            return 0;
        }
        remember(g_poll_reply, &g_poll_session, ev);
        if (g_backend->request_poll() != 0) {
            post_done(g_poll_reply, g_poll_session, TA_EV_NET_POLL_DONE);
            g_poll_reply[0] = '\0';
        }
        return 0;
    case TA_EV_NET_SET:
        g_stats.set++;
        g_stats.handled++;
        if (g_backend == NULL) {
            maybe_reply_immediate(ev, TA_EV_NET_SET_DONE);
            return 0;
        }
        remember(g_set_reply, &g_set_session, ev);
        {
            int rc = -1;
            uint8_t op = TA_NET_SET_OP_VOLUME;
            if (ev->payload_len >= 1) {
                op = ev->payload[0];
            }
            if (op == TA_NET_SET_OP_TOGGLE) {
                if (g_backend->request_toggle != NULL) {
                    rc = g_backend->request_toggle();
                }
            } else if (g_backend->request_volume != NULL &&
                       ev->payload_len >= 2) {
                rc = g_backend->request_volume((int)ev->payload[1]);
            } else if (g_backend->request_volume != NULL &&
                       ev->payload_len == 1) {
                /* Single byte: treat as absolute volume 0..100. */
                rc = g_backend->request_volume((int)ev->payload[0]);
            }
            if (rc != 0) {
                post_done(g_set_reply, g_set_session, TA_EV_NET_SET_DONE);
                g_set_reply[0] = '\0';
            }
        }
        return 0;
    case TA_EV_NET_ALBUMART:
        g_stats.albumart++;
        g_stats.handled++;
        if (g_backend == NULL || g_backend->request_albumart == NULL) {
            maybe_reply_immediate(ev, TA_EV_NET_ALBUMART_DONE);
            return 0;
        }
        remember(g_art_reply, &g_art_session, ev);
        {
            char path[TA_PAYLOAD_MAX + 1];
            size_t n = ev->payload_len;
            if (n > TA_PAYLOAD_MAX) {
                n = TA_PAYLOAD_MAX;
            }
            memcpy(path, ev->payload, n);
            path[n] = '\0';
            if (g_backend->request_albumart(path, 512u * 1024u) != 0) {
                post_done(g_art_reply, g_art_session, TA_EV_NET_ALBUMART_DONE);
                g_art_reply[0] = '\0';
            }
        }
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
