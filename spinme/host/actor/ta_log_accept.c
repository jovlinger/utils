#include "ta_log_accept.h"

#include "ta_event.h"
#include "ta_kv.h"
#include "ta_kv_actor.h"
#include "ta_log_rings.h"
#include "ta_net_events.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static ta_log_accept_event_t *g_snap;
static size_t g_snap_n;
static size_t g_snap_cap;
static unsigned g_rejected;
static ta_log_send_fn g_send;
static void *g_send_ud;
static char g_url[128];
static uint32_t g_last_empty_ms;
static int g_have_last;
static uint32_t g_cadence_s = TA_LOG_CADENCE_S_DEFAULT;
static uint16_t g_buffer_kb = TA_LOG_BUFFER_KB_DEFAULT;

static size_t ring_total_count(void) {
    return (size_t)ta_log_rings_count(TA_LOG_RING_ERROR) +
           (size_t)ta_log_rings_count(TA_LOG_RING_WARN) +
           (size_t)ta_log_rings_count(TA_LOG_RING_INFO);
}

static int rebuild_snap(void) {
    ta_log_rings_iter_t it;
    ta_log_rings_entry_t ent;
    size_t need;
    size_t n;

    need = ring_total_count();
    if (need > g_snap_cap) {
        ta_log_accept_event_t *ns;
        size_t cap;

        cap = need < 8u ? 8u : need;
        ns = (ta_log_accept_event_t *)realloc(g_snap, cap * sizeof(*ns));
        if (ns == NULL) {
            return -1;
        }
        g_snap = ns;
        g_snap_cap = cap;
    }
    memset(&it, 0, sizeof(it));
    if (ta_log_rings_iter_begin(&it) != 0) {
        g_snap_n = 0;
        return -1;
    }
    n = 0;
    while (ta_log_rings_iter_next(&it, &ent) != 0) {
        size_t len;

        if (n >= g_snap_cap) {
            break;
        }
        g_snap[n].emit_time_ms = (uint32_t)ent.time_ms;
        len = ent.text != NULL ? strlen(ent.text) : 0;
        if (len >= TA_LOG_MSG_MAX) {
            len = TA_LOG_MSG_MAX - 1;
        }
        if (len > 0) {
            memcpy(g_snap[n].message, ent.text, len);
        }
        g_snap[n].message[len] = '\0';
        n++;
    }
    ta_log_rings_iter_end(&it);
    g_snap_n = n;
    return 0;
}

void ta_log_accept_reset(void) {
    free(g_snap);
    g_snap = NULL;
    g_snap_n = 0;
    g_snap_cap = 0;
    g_rejected = 0;
    g_send = NULL;
    g_send_ud = NULL;
    g_url[0] = '\0';
    g_last_empty_ms = 0;
    g_have_last = 0;
    g_cadence_s = TA_LOG_CADENCE_S_DEFAULT;
    g_buffer_kb = TA_LOG_BUFFER_KB_DEFAULT;
    (void)ta_log_rings_reset();
    /* Host default: small arena so unit tests stay light. */
    ta_log_set_buffer_kb(g_buffer_kb);
}

void ta_log_set_buffer_kb(uint16_t kb) {
    uint32_t total;
    uint32_t err_b;
    uint32_t warn_b;
    uint32_t info_b;

    if (kb < 1u) {
        kb = 1u;
    }
    if (kb > TA_LOG_BUFFER_KB_MAX) {
        kb = (uint16_t)TA_LOG_BUFFER_KB_MAX;
    }
    g_buffer_kb = kb;
    total = (uint32_t)kb * 1024u;
    /* 1:1:2 split matching the 128/128/256 design. */
    err_b = total / 4u;
    warn_b = total / 4u;
    info_b = total - err_b - warn_b;
    if (err_b < 64u) {
        err_b = 64u;
    }
    if (warn_b < 64u) {
        warn_b = 64u;
    }
    if (info_b < 64u) {
        info_b = 64u;
    }
    (void)ta_log_rings_set_caps(err_b, warn_b, info_b);
    g_snap_n = 0;
}

size_t ta_log_buffer_cap(void) {
    uint32_t bytes;

    bytes = ta_log_rings_cap(TA_LOG_RING_ERROR) +
            ta_log_rings_cap(TA_LOG_RING_WARN) +
            ta_log_rings_cap(TA_LOG_RING_INFO);
    if (bytes < sizeof(ta_log_accept_event_t)) {
        return 1u;
    }
    return (size_t)(bytes / sizeof(ta_log_accept_event_t));
}

void ta_log_set_cadence_s(uint32_t seconds) {
    if (seconds < 1u) {
        seconds = 1u;
    }
    g_cadence_s = seconds;
}

uint32_t ta_log_cadence_s(void) {
    return g_cadence_s;
}

void ta_log_set_sender(ta_log_send_fn fn, void *ud) {
    g_send = fn;
    g_send_ud = ud;
}

void ta_log_set_url(const char *url) {
    size_t n;

    g_url[0] = '\0';
    if (url == NULL || url[0] == '\0') {
        return;
    }
    n = strlen(url);
    if (n >= sizeof(g_url)) {
        n = sizeof(g_url) - 1;
    }
    memcpy(g_url, url, n);
    g_url[n] = '\0';
}

const char *ta_log_url(void) {
    return g_url;
}

int ta_log_dump(uint32_t now_ms) {
    ta_log_rings_iter_t it;
    ta_log_rings_entry_t ent;
    uint32_t max_seq;
    int send_rc;
    char batch[TA_NET_LOG_DRAIN_MAX];
    size_t batch_n;

    if (rebuild_snap() != 0) {
        return -1;
    }
    max_seq = 0;
    batch_n = 0;
    memset(&it, 0, sizeof(it));
    if (ta_log_rings_iter_begin(&it) == 0) {
        while (ta_log_rings_iter_next(&it, &ent) != 0) {
            char line[160];
            size_t ln;
            int pri;

            if (ent.seq > max_seq) {
                max_seq = ent.seq;
            }
            pri = 14; /* user.info */
            if (ent.level == TA_LOG_LEVEL_ERROR) {
                pri = 11; /* user.err */
            } else if (ent.level == TA_LOG_LEVEL_WARN) {
                pri = 12; /* user.warning */
            }
            ln = (size_t)snprintf(
                line, sizeof(line), "<%d>1 %llu spinme spinme - - %s", pri,
                (unsigned long long)ent.time_ms,
                ent.text != NULL ? ent.text : "");
            if (ln >= sizeof(line)) {
                ln = sizeof(line) - 1;
            }
            if (ent.repeat > 1u) {
                char rep[48];
                int rn;

                rn = snprintf(rep, sizeof(rep), " (repeated %u times)",
                              (unsigned)ent.repeat);
                if (rn > 0 && (size_t)rn < sizeof(rep) &&
                    ln + (size_t)rn < sizeof(line)) {
                    memcpy(line + ln, rep, (size_t)rn);
                    ln += (size_t)rn;
                    line[ln] = '\0';
                }
            }
            if (batch_n + ln + 1u > sizeof(batch)) {
                break;
            }
            memcpy(batch + batch_n, line, ln);
            batch_n += ln;
            batch[batch_n++] = '\n';
        }
        ta_log_rings_iter_end(&it);
    }

    send_rc = 0;
    if (g_snap_n > 0 && g_send != NULL && g_url[0] != '\0') {
        send_rc = g_send(g_url, g_snap, g_snap_n, g_send_ud);
    } else if (batch_n > 0 && g_url[0] == '\0') {
        /* No URL: treat as local-only; do not advance heads. */
        send_rc = -1;
    }

    if (send_rc == 0 && g_snap_n > 0) {
        (void)ta_log_rings_ack_through(max_seq);
        g_snap_n = 0;
        g_last_empty_ms = now_ms;
        g_have_last = 1;
    }
    /* Failed or unreachable QuLog: leave rings; retry on next dump/tick. */
    (void)batch;
    return 0;
}

int ta_log_on_empty_tick(uint32_t now_ms) {
    uint32_t due_ms;

    due_ms = g_cadence_s * 1000u;
    if (due_ms > 30000u) {
        due_ms -= 30000u;
    } else if (due_ms > 1000u) {
        due_ms -= 1000u;
    }
    if (g_have_last && (now_ms - g_last_empty_ms) <= due_ms) {
        return 0;
    }
    return ta_log_dump(now_ms);
}

uint32_t ta_log_last_empty_ms(void) {
    return g_last_empty_ms;
}

void ta_log_apply_kv_settings(void) {
    int32_t kb;
    int32_t cadence;
    char target[TA_KV_VAL_MAX];
    size_t len;

    if (ta_kv_get_smallint(TA_KV_KEY_LOG_BUFFER_KB, &kb) == TA_KV_OK) {
        ta_log_set_buffer_kb((uint16_t)kb);
    }
    if (ta_kv_get_smallint(TA_KV_KEY_LOG_CADENCE_S, &cadence) == TA_KV_OK) {
        ta_log_set_cadence_s((uint32_t)cadence);
    }
    if (ta_kv_get(TA_KV_KEY_LOGTARGET, target, sizeof(target), &len) ==
        TA_KV_OK) {
        if (len >= sizeof(target)) {
            len = sizeof(target) - 1;
        }
        target[len] = '\0';
        ta_log_set_url(target);
    } else if (ta_kv_get(TA_KV_KEY_LOG_URL, target, sizeof(target), &len) ==
               TA_KV_OK) {
        if (len >= sizeof(target)) {
            len = sizeof(target) - 1;
        }
        target[len] = '\0';
        ta_log_set_url(target);
    }
}

int ta_log_handle_envelope(const ta_event_envelope_t *env) {
    const ta_all_inform_result_t *info;
    char url[TA_ALL_INFORM_MAX + 1];

    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_DEBUG_STATUS) {
        char line[48];

        snprintf(line, sizeof(line), "rings=%lu",
                 (unsigned long)ta_log_accept_count());
        return ta_debug_status_reply(env, "Log", line);
    }
    if (env->event.type == TA_EV_LIST_EVENTS) {
        return ta_list_events_offer(
            env, "list_events,debug_status,allperforminit");
    }
    if (env->event.type == TA_EV_ALL_PERFORM_INIT) {
        ta_log_apply_kv_settings();
        if (ta_kv_has(TA_KV_KEY_LOGTARGET)) {
            return ta_kv_actor_get("Log", TA_KV_KEY_LOGTARGET);
        }
        return ta_kv_actor_get("Log", TA_KV_KEY_LOG_URL);
    }
    if (env->event.type == TA_EV_NET_LOG_DRAIN_ACK) {
        if (env->event.u.net_log_drain_ack.status == 0) {
            (void)ta_log_rings_ack_through(
                env->event.u.net_log_drain_ack.max_seq);
            g_snap_n = 0;
            g_last_empty_ms = ta_now_ms();
            g_have_last = 1;
        }
        return 0;
    }
    if (env->event.type != TA_EV_ALL_INFORM_RESULT) {
        return 0;
    }
    info = &env->event.u.all_inform_result;
    if (strcmp(info->key, TA_KV_KEY_LOGTARGET) != 0 &&
        strcmp(info->key, TA_KV_KEY_LOG_URL) != 0) {
        return 0;
    }
    if (info->status != 0 || info->n == 0 || info->n > TA_ALL_INFORM_MAX) {
        return 0;
    }
    memcpy(url, info->bytes, info->n);
    url[info->n] = '\0';
    ta_log_set_url(url);
    return 0;
}

int ta_log_accept_level(uint8_t level, uint32_t emit_time_ms,
                        const char *message) {
    size_t n;

    if (message == NULL || message[0] == '\0') {
        g_rejected++;
        return -1;
    }
    n = strlen(message);
    if (n >= TA_LOG_MSG_MAX) {
        g_rejected++;
        return -1;
    }
    if (ta_log_rings_insert(level, (uint64_t)emit_time_ms, message) != 0) {
        g_rejected++;
        return -1;
    }
    (void)rebuild_snap();
    return 0;
}

int ta_log_accept(uint32_t emit_time_ms, const char *message) {
    return ta_log_accept_level(TA_LOG_LEVEL_INFO, emit_time_ms, message);
}

size_t ta_log_accept_count(void) {
    return ring_total_count();
}

const ta_log_accept_event_t *ta_log_accept_at(size_t index) {
    if (rebuild_snap() != 0) {
        return NULL;
    }
    if (index >= g_snap_n) {
        return NULL;
    }
    return &g_snap[index];
}

unsigned ta_log_accept_rejected(void) {
    return g_rejected;
}

size_t ta_log_format_syslog(char *dst, size_t cap, uint32_t emit_time_ms,
                            const char *message) {
    int n;

    if (dst == NULL || cap == 0 || message == NULL) {
        return 0;
    }
    /* PRI=14 (user.info). Timestamp is ms since boot (host/device stub). */
    n = snprintf(dst, cap, "<14>1 %u spinme spinme - - %s",
                 (unsigned)emit_time_ms, message);
    if (n < 0) {
        dst[0] = '\0';
        return 0;
    }
    if ((size_t)n >= cap) {
        return cap - 1;
    }
    return (size_t)n;
}

void ta_log_start(void) {
    (void)ta_registry_register("Log", ta_log_handle_envelope);
}
