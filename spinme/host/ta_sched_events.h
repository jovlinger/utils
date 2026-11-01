/* Scheduler TaskActor event interface (API + stub; fake time). */
#ifndef SPINME_TA_SCHED_EVENTS_H
#define SPINME_TA_SCHED_EVENTS_H

#include "ta_event.h"

#include <stdint.h>

#define TA_SCHED_NAME "Scheduler"

enum {
    TA_EV_SCHED_START = 0x500, /* start periodic/one-shot; payload: period_ms */
    TA_EV_SCHED_STOP = 0x501,  /* stop timer id in payload */
    TA_EV_SCHED_TICK = 0x502   /* internal/fake tick advance */
};

typedef struct ta_sched_stats {
    unsigned handled;
    unsigned unknown;
    unsigned starts;
    unsigned stops;
    unsigned ticks;
    unsigned fired;
} ta_sched_stats_t;

void ta_sched_reset(void);
void ta_sched_start(void);
int ta_sched_enqueue(const ta_event_t *ev);
int ta_sched_handle(const ta_event_t *ev);
/* Advance fake clock; fire due one-shots/periodics to dst. */
void ta_sched_advance_ms(uint32_t ms);
uint32_t ta_sched_now_ms(void);
const ta_sched_stats_t *ta_sched_stats(void);

#endif
