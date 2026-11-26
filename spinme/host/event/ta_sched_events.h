/* Scheduler TaskActor: clock / scroll / one-off cadences (fake time). */
#ifndef SPINME_TA_SCHED_EVENTS_H
#define SPINME_TA_SCHED_EVENTS_H

#include "ta_event.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif


#define TA_SCHED_NAME "Scheduler"

enum {
    TA_EV_SCHED_START = 0x500, /* period_ms u32 + flags u8 (bit0=oneshot) */
    TA_EV_SCHED_STOP = 0x501,
    TA_EV_SCHED_TICK = 0x502
};

#define TA_SCHED_FLAG_ONESHOT 0x01u

typedef struct ta_sched_stats {
    unsigned handled;
    unsigned unknown;
    unsigned starts;
    unsigned stops;
    unsigned ticks;
    unsigned fired;
    unsigned oneshots_fired;
    unsigned clock_fires;
    unsigned scroll_fires;
} ta_sched_stats_t;

void ta_sched_reset(void);
void ta_sched_start(void);
int ta_sched_enqueue(const ta_event_envelope_t *env);
int ta_sched_handle(const ta_event_envelope_t *env);
void ta_sched_advance_ms(uint32_t ms);
uint32_t ta_sched_now_ms(void);
const ta_sched_stats_t *ta_sched_stats(void);

/* Convenience arms (post START to Scheduler). */
int ta_sched_arm_clock_1hz(const char *dst, ta_session_id_t session);
int ta_sched_arm_scroll(const char *dst, ta_session_id_t session,
                        uint32_t every_ms);
int ta_sched_arm_oneshot(const char *dst, ta_session_id_t session,
                         uint32_t delay_ms, ta_event_type_t fire_type);
/* Generic repeating cadence: fire_type to dst every every_ms (no payload). */
int ta_sched_arm_periodic(const char *dst, ta_session_id_t session,
                          uint32_t every_ms, ta_event_type_t fire_type);


#ifdef __cplusplus
}
#endif
#endif
