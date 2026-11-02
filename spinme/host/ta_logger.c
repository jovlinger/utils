#include "ta_logger.h"

#include "ta_queue.h"
#include "ta_registry.h"

#include <stdio.h>
#include <string.h>

#define TA_LOGGER_QCAP 16
#define TA_LOG_SEV_MAX 8

static ta_event_t g_slots[TA_LOGGER_QCAP];
static ta_queue_t g_q;
static int g_q_ok;
static ta_log_policy_t g_policy[TA_LOG_SEV_MAX];
static ta_log_stats_t g_stats;

void ta_logger_reset(void) {
    size_t i;

    if (g_q_ok) {
        ta_queue_fini(&g_q);
        g_q_ok = 0;
    }
    memset(&g_stats, 0, sizeof(g_stats));
    for (i = 0; i < TA_LOG_SEV_MAX; i++) {
        g_policy[i] = TA_LOG_POLICY_DROP;
    }
}

void ta_logger_set_policy(uint8_t severity, ta_log_policy_t policy) {
    if (severity < TA_LOG_SEV_MAX) {
        g_policy[severity] = policy;
    }
}

ta_log_policy_t ta_logger_policy(uint8_t severity) {
    if (severity >= TA_LOG_SEV_MAX) {
        return TA_LOG_POLICY_DROP;
    }
    return g_policy[severity];
}

int ta_logger_enqueue(const ta_event_t *ev) {
    if (!g_q_ok || ev == NULL) {
        return -1;
    }
    return ta_queue_push(&g_q, ev);
}

static void apply_policy(const ta_event_t *ev) {
    uint8_t sev;
    char prefix[48];
    const char *text;
    size_t text_len;

    g_stats.accepted++;
    sev = 0;
    text = "";
    text_len = 0;
    if (ev->payload_len >= 1) {
        sev = ev->payload[0];
    }
    if (ev->payload_len >= 3) {
        text = (const char *)&ev->payload[2];
        text_len = (size_t)(ev->payload_len - 2);
    }

    ta_log_prefix(prefix, sizeof(prefix), 0, ev->session_id, ev->src);

    switch (ta_logger_policy(sev)) {
    case TA_LOG_POLICY_NVM:
        /* Stub: count only until KV exists. */
        g_stats.nvm++;
        (void)text;
        (void)text_len;
        break;
    case TA_LOG_POLICY_EXTERNAL:
        g_stats.external++;
        fprintf(stderr, "%s %.*s\n", prefix, (int)text_len, text);
        break;
    case TA_LOG_POLICY_DROP:
    default:
        g_stats.dropped++;
        break;
    }
}

size_t ta_logger_drain(size_t max) {
    size_t n = 0;
    ta_event_t ev;

    if (!g_q_ok) {
        return 0;
    }
    while (n < max) {
        if (ta_queue_try_peek(&g_q, &ev) != 0) {
            break;
        }
        apply_policy(&ev);
        ta_queue_pop(&g_q);
        n++;
    }
    return n;
}

const ta_log_stats_t *ta_logger_stats(void) {
    return &g_stats;
}

void ta_logger_start(void) {
    if (!g_q_ok) {
        if (ta_queue_init(&g_q, g_slots, TA_LOGGER_QCAP) != 0) {
            return;
        }
        g_q_ok = 1;
    }
    (void)ta_registry_register(TA_LOGGER_NAME, ta_logger_enqueue);
}

int ta_logger_emit(ta_session_id_t session, const char *src, uint8_t severity,
                   uint8_t tag, const char *text) {
    ta_event_t ev;
    uint8_t buf[TA_PAYLOAD_MAX];
    size_t tlen;
    size_t need;

    ta_event_clear(&ev);
    ev.type = TA_EV_LOG;
    ev.session_id = session;
    if (ta_event_set_src(&ev, src != NULL ? src : "?") != 0) {
        return -1;
    }
    if (text == NULL) {
        text = "";
    }
    tlen = strlen(text);
    need = 2 + tlen;
    if (need > TA_PAYLOAD_MAX) {
        tlen = TA_PAYLOAD_MAX - 2;
        need = TA_PAYLOAD_MAX;
    }
    buf[0] = severity;
    buf[1] = tag;
    if (tlen > 0) {
        memcpy(buf + 2, text, tlen);
    }
    if (ta_event_set_payload(&ev, buf, need) != 0) {
        return -1;
    }
    return ta_registry_post(TA_LOGGER_NAME, &ev);
}
