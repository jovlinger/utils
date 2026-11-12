#include "ta_log_accept.h"

#include "ta_event.h"
#include "ta_kv.h"
#include "ta_kv_actor.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Heap buffer: max 128 KiB must not sit in ESP32 DRAM BSS. */
static ta_log_accept_event_t *g_buf;
static size_t g_cap;
static size_t g_n;
static unsigned g_rejected;
static ta_log_send_fn g_send;
static void *g_send_ud;
static char g_url[128];
static uint32_t g_last_empty_ms;
static int g_have_last;
static uint32_t g_cadence_s = TA_LOG_CADENCE_S_DEFAULT;

static int ensure_buf(size_t slots) {
    ta_log_accept_event_t *nbuf;

    if (slots < 1u) {
        slots = 1u;
    }
    if (g_buf != NULL && g_cap == slots) {
        return 0;
    }
    nbuf = (ta_log_accept_event_t *)realloc(g_buf, slots * sizeof(*nbuf));
    if (nbuf == NULL) {
        return -1;
    }
    if (slots > g_cap) {
        memset(nbuf + g_cap, 0, (slots - g_cap) * sizeof(*nbuf));
    }
    g_buf = nbuf;
    g_cap = slots;
    if (g_n > g_cap) {
        g_n = g_cap;
    }
    return 0;
}

void ta_log_accept_reset(void) {
    free(g_buf);
    g_buf = NULL;
    g_cap = 0;
    g_n = 0;
    g_rejected = 0;
    g_send = NULL;
    g_send_ud = NULL;
    g_url[0] = '\0';
    g_last_empty_ms = 0;
    g_have_last = 0;
    g_cadence_s = TA_LOG_CADENCE_S_DEFAULT;
    (void)ensure_buf(TA_LOG_ACCEPT_DEFAULT_CAP);
}

void ta_log_set_buffer_kb(uint16_t kb) {
    size_t bytes;
    size_t slots;

    if (kb < 1u) {
        kb = 1u;
    }
    if (kb > TA_LOG_BUFFER_KB_MAX) {
        kb = (uint16_t)TA_LOG_BUFFER_KB_MAX;
    }
    bytes = (size_t)kb * 1024u;
    if (bytes > TA_LOG_ACCEPT_BYTES_MAX) {
        bytes = TA_LOG_ACCEPT_BYTES_MAX;
    }
    slots = bytes / sizeof(ta_log_accept_event_t);
    if (slots < 1u) {
        slots = 1u;
    }
    if (slots > TA_LOG_ACCEPT_MAX_EVENTS) {
        slots = TA_LOG_ACCEPT_MAX_EVENTS;
    }
    (void)ensure_buf(slots);
}

size_t ta_log_buffer_cap(void) {
    return g_cap;
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
    if (g_buf == NULL && ensure_buf(TA_LOG_ACCEPT_DEFAULT_CAP) != 0) {
        return -1;
    }
    if (g_n > 0 && g_send != NULL && g_url[0] != '\0') {
        (void)g_send(g_url, g_buf, g_n, g_send_ud);
    }
    g_n = 0;
    memset(g_buf, 0, sizeof(g_buf[0]) * g_cap);
    g_last_empty_ms = now_ms;
    g_have_last = 1;
    return 0;
}

int ta_log_on_empty_tick(uint32_t now_ms) {
    uint32_t due_ms;

    /* Dump when cadence window nearly elapsed (cadence - 30s, min 1s). */
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
    if (env->event.type == TA_EV_ALL_PERFORM_INIT) {
        ta_log_apply_kv_settings();
        if (ta_kv_has(TA_KV_KEY_LOGTARGET)) {
            return ta_kv_actor_get("Log", TA_KV_KEY_LOGTARGET);
        }
        return ta_kv_actor_get("Log", TA_KV_KEY_LOG_URL);
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

int ta_log_accept(uint32_t emit_time_ms, const char *message) {
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
    if (g_buf == NULL && ensure_buf(TA_LOG_ACCEPT_DEFAULT_CAP) != 0) {
        g_rejected++;
        return -1;
    }
    if (g_n >= g_cap) {
        g_rejected++;
        return -1;
    }
    g_buf[g_n].emit_time_ms = emit_time_ms;
    memcpy(g_buf[g_n].message, message, n + 1);
    g_n++;
    if (g_n >= g_cap) {
        (void)ta_log_dump(emit_time_ms);
    }
    return 0;
}

size_t ta_log_accept_count(void) {
    return g_n;
}

const ta_log_accept_event_t *ta_log_accept_at(size_t index) {
    if (index >= g_n) {
        return NULL;
    }
    return &g_buf[index];
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
