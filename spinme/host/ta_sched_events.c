#include "ta_sched_events.h"

#include "ta_registry.h"

#include <stddef.h>
#include <string.h>

#define TA_SCHED_SLOTS 8

typedef struct {
    int used;
    uint32_t period_ms;
    uint32_t next_ms;
    char dst[TA_NAME_MAX];
    ta_event_type_t fire_type;
    ta_session_id_t session_id;
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

static int start_timer(const ta_event_t *ev) {
    size_t i;
    uint32_t period;
    ta_sched_slot_t *s;

    if (ev->payload_len < 4 || ev->reply_to[0] == '\0') {
        return -1;
    }
    period = (uint32_t)ev->payload[0] | ((uint32_t)ev->payload[1] << 8) |
             ((uint32_t)ev->payload[2] << 16) | ((uint32_t)ev->payload[3] << 24);
    if (period == 0) {
        return -1;
    }
    for (i = 0; i < TA_SCHED_SLOTS; i++) {
        if (!g_slots[i].used) {
            s = &g_slots[i];
            s->used = 1;
            s->period_ms = period;
            s->next_ms = g_now_ms + period;
            memcpy(s->dst, ev->reply_to, TA_NAME_MAX);
            s->fire_type = ev->reply_type != 0 ? ev->reply_type : TA_EV_NOP;
            s->session_id = ev->session_id;
            g_stats.starts++;
            return 0;
        }
    }
    return -1;
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

void ta_sched_advance_ms(uint32_t ms) {
    size_t i;
    ta_event_t fire;

    g_now_ms += ms;
    for (i = 0; i < TA_SCHED_SLOTS; i++) {
        ta_sched_slot_t *s = &g_slots[i];

        while (s->used && g_now_ms >= s->next_ms) {
            ta_event_clear(&fire);
            fire.type = s->fire_type;
            fire.session_id = s->session_id;
            (void)ta_event_set_src(&fire, TA_SCHED_NAME);
            (void)ta_registry_post(s->dst, &fire);
            g_stats.fired++;
            s->next_ms += s->period_ms;
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
            uint32_t step = (uint32_t)ev->payload[0] |
                            ((uint32_t)ev->payload[1] << 8) |
                            ((uint32_t)ev->payload[2] << 16) |
                            ((uint32_t)ev->payload[3] << 24);
            ta_sched_advance_ms(step);
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
