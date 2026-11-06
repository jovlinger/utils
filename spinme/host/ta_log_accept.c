#include "ta_log_accept.h"

#include <string.h>

static ta_log_accept_event_t g_buf[TA_LOG_ACCEPT_CAP];
static size_t g_n;
static unsigned g_rejected;

void ta_log_accept_reset(void) {
    memset(g_buf, 0, sizeof(g_buf));
    g_n = 0;
    g_rejected = 0;
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
