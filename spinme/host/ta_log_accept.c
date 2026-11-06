#include "ta_log_accept.h"

#include "ta_event.h"
#include "ta_kv_actor.h"

#include <string.h>

static ta_log_accept_event_t g_buf[TA_LOG_ACCEPT_CAP];
static size_t g_n;
static unsigned g_rejected;
static ta_log_send_fn g_send;
static void *g_send_ud;
static char g_url[128];
static uint32_t g_last_empty_ms;
static int g_have_last;

void ta_log_accept_reset(void) {
    memset(g_buf, 0, sizeof(g_buf));
    g_n = 0;
    g_rejected = 0;
    g_send = NULL;
    g_send_ud = NULL;
    g_url[0] = '\0';
    g_last_empty_ms = 0;
    g_have_last = 0;
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

int ta_log_dump(uint32_t now_ms) {
    if (g_n > 0 && g_send != NULL && g_url[0] != '\0') {
        (void)g_send(g_url, g_buf, g_n, g_send_ud);
    }
    g_n = 0;
    memset(g_buf, 0, sizeof(g_buf));
    g_last_empty_ms = now_ms;
    g_have_last = 1;
    return 0;
}

int ta_log_on_empty_tick(uint32_t now_ms) {
    if (g_have_last && (now_ms - g_last_empty_ms) <= TA_LOG_EMPTY_DUE_MS) {
        return 0;
    }
    return ta_log_dump(now_ms);
}

uint32_t ta_log_last_empty_ms(void) {
    return g_last_empty_ms;
}

int ta_log_handle_envelope(const ta_event_envelope_t *env) {
    const ta_all_inform_result_t *info;
    char url[TA_ALL_INFORM_MAX + 1];

    if (env == NULL) {
        return -1;
    }
    if (env->event.type == TA_EV_ALL_PERFORM_INIT) {
        return ta_kv_actor_get("Log", TA_KV_KEY_LOG_URL);
    }
    if (env->event.type != TA_EV_ALL_INFORM_RESULT) {
        return 0;
    }
    info = &env->event.u.all_inform_result;
    if (strcmp(info->key, TA_KV_KEY_LOG_URL) != 0) {
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
    if (g_n >= TA_LOG_ACCEPT_CAP) {
        g_rejected++;
        return -1;
    }
    g_buf[g_n].emit_time_ms = emit_time_ms;
    memcpy(g_buf[g_n].message, message, n + 1);
    g_n++;
    if (g_n >= TA_LOG_ACCEPT_CAP) {
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
