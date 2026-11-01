/* ISR -> Draw ingress. Host stand-in for FreeRTOS xQueueSendFromISR.
 *
 * No pthread/task mutex on the FromISR path. Never call Wi-Fi, paint, or Net
 * from this API. Device maps push_from_isr to xQueueSendFromISR into Draw.
 */
#ifndef SPINME_TA_ISR_MAIL_H
#define SPINME_TA_ISR_MAIL_H

#include "ta_event.h"
#include "ta_queue.h"

#include <stddef.h>
#include <stdint.h>

#define TA_ISR_MAIL_CAP 8

/* Allowed ISR event types (extend carefully; keep decode in task). */
enum {
    TA_EV_ISR_TOUCH = 0x100,
    TA_EV_ISR_ROTARY = 0x101
};

typedef struct ta_isr_mail {
    ta_event_t slots[TA_ISR_MAIL_CAP];
    volatile uint32_t head; /* consumer */
    volatile uint32_t tail; /* producer (ISR) */
    volatile unsigned drops;
} ta_isr_mail_t;

void ta_isr_mail_reset(ta_isr_mail_t *m);

/* FromISR: no task mutex. Returns 0, or -1 if full (drops++, never blocks). */
int ta_isr_mail_push_from_isr(ta_isr_mail_t *m, const ta_event_t *ev);

/* Task context: move pending ISR events into Draw's MP/SC queue. */
size_t ta_isr_mail_drain_to_queue(ta_isr_mail_t *m, ta_queue_t *draw_q);

#endif
