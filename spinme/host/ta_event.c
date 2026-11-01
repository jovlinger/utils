#include "ta_event.h"

#include <stdio.h>
#include <string.h>

void ta_event_clear(ta_event_t *ev) {
    if (ev == NULL) {
        return;
    }
    memset(ev, 0, sizeof(*ev));
}

static int copy_name(char *dst, const char *name) {
    size_t n;

    if (dst == NULL || name == NULL || name[0] == '\0') {
        return -1;
    }
    n = strlen(name);
    if (n >= TA_NAME_MAX) {
        return -1;
    }
    memcpy(dst, name, n + 1);
    return 0;
}

int ta_event_set_src(ta_event_t *ev, const char *name) {
    if (ev == NULL) {
        return -1;
    }
    return copy_name(ev->src, name);
}

int ta_event_set_reply(ta_event_t *ev, const char *actor, ta_event_type_t type) {
    if (ev == NULL) {
        return -1;
    }
    if (copy_name(ev->reply_to, actor) != 0) {
        return -1;
    }
    ev->reply_type = type;
    return 0;
}

int ta_event_set_payload(ta_event_t *ev, const void *bytes, size_t len) {
    if (ev == NULL) {
        return -1;
    }
    if (len > TA_PAYLOAD_MAX) {
        return -1;
    }
    if (len > 0 && bytes == NULL) {
        return -1;
    }
    if (len > 0) {
        memcpy(ev->payload, bytes, len);
    }
    ev->payload_len = (uint16_t)len;
    return 0;
}

size_t ta_log_prefix(char *buf, size_t cap, uint32_t time_ms,
                     ta_session_id_t session, const char *actor) {
    int n;

    if (buf == NULL || cap == 0) {
        return 0;
    }
    if (actor == NULL) {
        actor = "?";
    }
    n = snprintf(buf, cap, "%u|%u|%s", (unsigned)time_ms, (unsigned)session,
                 actor);
    if (n < 0) {
        buf[0] = '\0';
        return 0;
    }
    if ((size_t)n >= cap) {
        return cap - 1;
    }
    return (size_t)n;
}
