#include "ta_sched_events.h"

#include "ta_draw_events.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <stddef.h>
#include <string.h>

#define TA_SCHED_SLOTS 16

typedef struct {
    int used;
    int oneshot;
    uint32_t period_ms;
    uint32_t next_ms;
    char dst[TA_NAME_MAX];
    ta_event_type_t fire_type;
    ta_session_id_t session_id;
    int16_t scroll_ox; /* advances on scroll cadence */
} ta_sched_slot_t;

static ta_sched_slot_t g_slots[TA_SCHED_SLOTS];
static ta_sched_stats_t g_stats;
static uint32_t g_now_ms;

void ta_sched_reset(void) {
    memset(g_slots, 0, sizeof(g_slots));
    memset(&g_stats, 0, sizeof(g_stats));
    g_now_ms = 0;
}

uint32_t ta_sched_now_ms(void) {
    return g_now_ms;
}

const ta_sched_stats_t *ta_sched_stats(void) {
    return &g_stats;
}

static int alloc_slot(void) {
    size_t i;

    /* One-offs front-packed: prefer first free from start. */
    for (i = 0; i < TA_SCHED_SLOTS; i++) {
        if (!g_slots[i].used) {
            return (int)i;
        }
    }
    return -1;
}

static int start_timer(const ta_event_envelope_t *env) {
    int idx;
    ta_sched_slot_t *s;
    const ta_sched_start_t *st = &env->event.u.sched_start;

    if (st->fire_to[0] == '\0' || st->period_ms == 0) {
        return -1;
    }
    idx = alloc_slot();
    if (idx < 0) {
        return -1;
    }
    s = &g_slots[idx];
    memset(s, 0, sizeof(*s));
    s->used = 1;
    s->oneshot = (st->flags & TA_SCHED_FLAG_ONESHOT) != 0;
    s->period_ms = st->period_ms;
    s->next_ms = g_now_ms + st->period_ms;
    memcpy(s->dst, st->fire_to, TA_NAME_MAX);
    s->fire_type = st->fire_type != 0 ? st->fire_type : TA_EV_NOP;
    s->session_id = env->session_id;
    g_stats.starts++;
    return 0;
}

static int stop_all(void) {
    size_t i;
    int n = 0;

    for (i = 0; i < TA_SCHED_SLOTS; i++) {
        if (g_slots[i].used) {
            g_slots[i].used = 0;
            n++;
        }
    }
    g_stats.stops += (unsigned)n;
    return 0;
}

static void fire_slot(ta_sched_slot_t *s) {
    ta_event_envelope_t fire;

    ta_env_clear(&fire);
    fire.event.type = s->fire_type;
    fire.session_id = s->session_id;
    (void)ta_env_set_src(&fire, TA_SCHED_NAME);
    if (s->fire_type == TA_EV_DRAW_SCROLL_OX) {
        s->scroll_ox = (int16_t)(s->scroll_ox + 1);
        fire.event.u.draw_scroll_ox.ox = s->scroll_ox;
        fire.event.u.draw_scroll_ox.has_ox = 1;
        g_stats.scroll_fires++;
    } else if (s->fire_type == TA_EV_DRAW_UPDATE) {
        fire.event.u.draw_update.kind = (uint8_t)TA_DRAW_UPD_CADENCE;
        g_stats.clock_fires++;
    }
    (void)ta_registry_post(s->dst, &fire);
    g_stats.fired++;
    if (s->oneshot) {
        s->used = 0;
        g_stats.oneshots_fired++;
    } else {
        /* Overdue: push one event, then schedule next from now+period
         * (not catch-up burst). */
        s->next_ms = g_now_ms + s->period_ms;
    }
}

void ta_sched_advance_ms(uint32_t ms) {
    size_t i;

    g_now_ms += ms;
    /* One-offs first (front of table), then permanents. */
    for (i = 0; i < TA_SCHED_SLOTS; i++) {
        ta_sched_slot_t *s = &g_slots[i];

        if (s->used && s->oneshot && g_now_ms >= s->next_ms) {
            fire_slot(s);
        }
    }
    for (i = 0; i < TA_SCHED_SLOTS; i++) {
        ta_sched_slot_t *s = &g_slots[i];

        if (s->used && !s->oneshot && g_now_ms >= s->next_ms) {
            fire_slot(s);
        }
    }
}

int ta_sched_handle(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    switch (env->event.type) {
    case TA_EV_SCHED_START:
        g_stats.handled++;
        return start_timer(env);
    case TA_EV_SCHED_STOP:
        g_stats.handled++;
        return stop_all();
    case TA_EV_SCHED_TICK:
        g_stats.ticks++;
        g_stats.handled++;
        ta_sched_advance_ms(env->event.u.sched_tick.advance_ms);
        return 0;
    case TA_EV_LIST_EVENTS:
        g_stats.handled++;
        return ta_list_events_offer(
            env, "list_events,schedstart,schedstop,schedtick");
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_sched_enqueue(const ta_event_envelope_t *env) {
    return ta_sched_handle(env);
}

void ta_sched_start(void) {
    (void)ta_registry_register(TA_SCHED_NAME, ta_sched_enqueue);
}

static int post_start(const char *dst, ta_session_id_t session, uint32_t period,
                      uint8_t flags, ta_event_type_t fire_type) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.event.type = TA_EV_SCHED_START;
    env.session_id = session;
    (void)ta_env_set_src(&env, "Init");
    if (ta_event_set_sched_start(&env.event, dst, fire_type, period, flags) !=
        0) {
        return -1;
    }
    return ta_registry_post(TA_SCHED_NAME, &env);
}

int ta_sched_arm_clock_1hz(const char *dst, ta_session_id_t session) {
    return post_start(dst, session, 1000, 0, TA_EV_DRAW_UPDATE);
}

int ta_sched_arm_scroll(const char *dst, ta_session_id_t session,
                        uint32_t every_ms) {
    return post_start(dst, session, every_ms, 0, TA_EV_DRAW_SCROLL_OX);
}

int ta_sched_arm_oneshot(const char *dst, ta_session_id_t session,
                         uint32_t delay_ms, ta_event_type_t fire_type) {
    return post_start(dst, session, delay_ms, TA_SCHED_FLAG_ONESHOT, fire_type);
}

int ta_sched_arm_periodic(const char *dst, ta_session_id_t session,
                          uint32_t every_ms, ta_event_type_t fire_type) {
    return post_start(dst, session, every_ms, 0, fire_type);
}
