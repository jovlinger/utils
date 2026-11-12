#include "ta_logger.h"

#include "ta_queue.h"
#include "ta_registry.h"

#include <stdio.h>
#include <string.h>

#define TA_LOGGER_QCAP 16
#define TA_LOG_SEV_MAX 8

static ta_event_envelope_t g_slots[TA_LOGGER_QCAP];
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

int ta_logger_enqueue(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_DEBUG_STATUS) {
        return ta_debug_status_reply(env, TA_LOGGER_NAME, "ok");
    }
    if (!g_q_ok) {
        return -1;
    }
    return ta_queue_push(&g_q, env);
}

static void apply_policy(const ta_event_envelope_t *env) {
    uint8_t sev;
    char prefix[48];
    const char *text;
    const ta_log_emit_line_t *line;

    g_stats.accepted++;
    line = &env->event.u.log_emit_line;
    sev = line->severity;
    text = line->text;

    ta_log_prefix(prefix, sizeof(prefix), env->enqueue_time_ms, env->session_id,
                  env->src);

    switch (ta_logger_policy(sev)) {
    case TA_LOG_POLICY_NVM:
        g_stats.nvm++;
        (void)text;
        break;
    case TA_LOG_POLICY_EXTERNAL:
        g_stats.external++;
        fprintf(stderr, "%s %s\n", prefix, text);
        break;
    case TA_LOG_POLICY_DROP:
    default:
        g_stats.dropped++;
        break;
    }
}

size_t ta_logger_drain(size_t max) {
    size_t n = 0;
    ta_event_envelope_t env;

    if (!g_q_ok) {
        return 0;
    }
    while (n < max) {
        if (ta_queue_try_peek(&g_q, &env) != 0) {
            break;
        }
        apply_policy(&env);
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
    ta_event_envelope_t env;
    size_t tlen;

    ta_env_clear(&env);
    env.session_id = session;
    env.event.type = TA_EV_LOG;
    if (ta_env_set_src(&env, src != NULL ? src : "?") != 0) {
        return -1;
    }
    if (text == NULL) {
        text = "";
    }
    tlen = strlen(text);
    if (tlen > TA_LOG_TEXT_MAX) {
        tlen = TA_LOG_TEXT_MAX;
    }
    env.event.u.log_emit_line.severity = severity;
    env.event.u.log_emit_line.tag = tag;
    memcpy(env.event.u.log_emit_line.text, text, tlen);
    env.event.u.log_emit_line.text[tlen] = '\0';
    return ta_registry_post(TA_LOGGER_NAME, &env);
}
