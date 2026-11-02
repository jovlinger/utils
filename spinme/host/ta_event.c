#include "ta_event.h"

#include <stdio.h>
#include <string.h>
#include <time.h>

void ta_event_clear(ta_event_t *ev) {
    if (ev == NULL) {
        return;
    }
    memset(ev, 0, sizeof(*ev));
}

void ta_env_clear(ta_event_envelope_t *env) {
    if (env == NULL) {
        return;
    }
    memset(env, 0, sizeof(*env));
}

int ta_copy_name(char *dst, size_t cap, const char *name) {
    size_t n;

    if (dst == NULL || cap == 0 || name == NULL || name[0] == '\0') {
        return -1;
    }
    n = strlen(name);
    if (n >= cap) {
        return -1;
    }
    memcpy(dst, name, n + 1);
    return 0;
}

int ta_env_set_src(ta_event_envelope_t *env, const char *name) {
    if (env == NULL) {
        return -1;
    }
    return ta_copy_name(env->src, TA_NAME_MAX, name);
}

int ta_event_set_net_poll_playerstate(ta_event_t *ev, const char *reply_to) {
    if (ev == NULL) {
        return -1;
    }
    memset(&ev->u, 0, sizeof(ev->u));
    if (ta_copy_name(ev->u.net_poll_playerstate.reply_to, TA_NAME_MAX,
                     reply_to) != 0) {
        return -1;
    }
    return 0;
}

int ta_event_set_net_set(ta_event_t *ev, const char *reply_to, uint8_t op,
                         ta_volume_t volume) {
    if (ev == NULL) {
        return -1;
    }
    memset(&ev->u, 0, sizeof(ev->u));
    if (reply_to != NULL && reply_to[0] != '\0') {
        if (ta_copy_name(ev->u.net_set.reply_to, TA_NAME_MAX, reply_to) != 0) {
            return -1;
        }
    }
    ev->u.net_set.op = op;
    ev->u.net_set.volume = volume;
    return 0;
}

int ta_event_set_ctrl_set_route(ta_event_t *ev, const char *target) {
    if (ev == NULL) {
        return -1;
    }
    memset(&ev->u, 0, sizeof(ev->u));
    return ta_copy_name(ev->u.ctrl_set_route.target, TA_NAME_MAX, target);
}

int ta_event_set_sched_start(ta_event_t *ev, const char *fire_to,
                             ta_event_type_t fire_type, uint32_t period_ms,
                             uint8_t flags) {
    if (ev == NULL) {
        return -1;
    }
    memset(&ev->u, 0, sizeof(ev->u));
    if (ta_copy_name(ev->u.sched_start.fire_to, TA_NAME_MAX, fire_to) != 0) {
        return -1;
    }
    ev->u.sched_start.fire_type = fire_type;
    ev->u.sched_start.period_ms = period_ms;
    ev->u.sched_start.flags = flags;
    return 0;
}

uint32_t ta_now_ms(void) {
#ifdef SPINME_TA_DEVICE
    /* esp_timer.h pulled by the firmware build; avoid host dependency. */
    extern int64_t esp_timer_get_time(void);
    return (uint32_t)(esp_timer_get_time() / 1000LL);
#else
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        return 0;
    }
    return (uint32_t)((uint64_t)ts.tv_sec * 1000u +
                      (uint64_t)ts.tv_nsec / 1000000u);
#endif
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
