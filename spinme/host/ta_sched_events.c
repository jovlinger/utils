#include "ta_sched_events.h"

#include "ta_draw_events.h"
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

static void put_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xff);
    p[1] = (uint8_t)((v >> 8) & 0xff);
    p[2] = (uint8_t)((v >> 16) & 0xff);
    p[3] = (uint8_t)((v >> 24) & 0xff);
}

static uint32_t get_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
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

static int start_timer(const ta_event_t *ev) {
    int idx;
    ta_sched_slot_t *s;
    uint32_t period;
    uint8_t flags = 0;

    if (ev->payload_len < 4 || ev->reply_to[0] == '\0') {
        return -1;
    }
    period = get_u32(ev->payload);
    if (ev->payload_len >= 5) {
        flags = ev->payload[4];
    }
    if (period == 0) {
        return -1;
    }
    idx = alloc_slot();
    if (idx < 0) {
        return -1;
    }
    s = &g_slots[idx];
    memset(s, 0, sizeof(*s));
    s->used = 1;
    s->oneshot = (flags & TA_SCHED_FLAG_ONESHOT) != 0;
    s->period_ms = period;
    s->next_ms = g_now_ms + period;
    memcpy(s->dst, ev->reply_to, TA_NAME_MAX);
    s->fire_type = ev->reply_type != 0 ? ev->reply_type : TA_EV_NOP;
    s->session_id = ev->session_id;
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
    ta_event_t fire;
    uint8_t ox[2];

    ta_event_clear(&fire);
    fire.type = s->fire_type;
    fire.session_id = s->session_id;
    (void)ta_event_set_src(&fire, TA_SCHED_NAME);
    if (s->fire_type == TA_EV_DRAW_SCROLL_OX) {
        s->scroll_ox = (int16_t)(s->scroll_ox + 1);
        ox[0] = (uint8_t)(s->scroll_ox & 0xff);
        ox[1] = (uint8_t)((s->scroll_ox >> 8) & 0xff);
        (void)ta_event_set_payload(&fire, ox, 2);
        g_stats.scroll_fires++;
    } else if (s->fire_type == TA_EV_DRAW_UPDATE) {
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

int ta_sched_handle(const ta_event_t *ev) {
    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_SCHED_START:
        g_stats.handled++;
        return start_timer(ev);
    case TA_EV_SCHED_STOP:
        g_stats.handled++;
        return stop_all();
    case TA_EV_SCHED_TICK:
        g_stats.ticks++;
        g_stats.handled++;
        if (ev->payload_len >= 4) {
            ta_sched_advance_ms(get_u32(ev->payload));
        }
        return 0;
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_sched_enqueue(const ta_event_t *ev) {
    return ta_sched_handle(ev);
}

void ta_sched_start(void) {
    (void)ta_registry_register(TA_SCHED_NAME, ta_sched_enqueue);
}

static int post_start(const char *dst, ta_session_id_t session, uint32_t period,
                      uint8_t flags, ta_event_type_t fire_type) {
    ta_event_t ev;
    uint8_t pl[5];

    ta_event_clear(&ev);
    ev.type = TA_EV_SCHED_START;
    ev.session_id = session;
    (void)ta_event_set_src(&ev, "Init");
    if (ta_event_set_reply(&ev, dst, fire_type) != 0) {
        return -1;
    }
    put_u32(pl, period);
    pl[4] = flags;
    if (ta_event_set_payload(&ev, pl, 5) != 0) {
        return -1;
    }
    return ta_registry_post(TA_SCHED_NAME, &ev);
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
