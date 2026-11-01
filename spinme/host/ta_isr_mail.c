#include "ta_isr_mail.h"

#include <stdio.h>
#include <string.h>

void ta_isr_mail_reset(ta_isr_mail_t *m) {
    if (m == NULL) {
        return;
    }
    memset(m, 0, sizeof(*m));
}

int ta_isr_mail_push_from_isr(ta_isr_mail_t *m, const ta_event_t *ev) {
    uint32_t head;
    uint32_t tail;
    uint32_t next;

    if (m == NULL || ev == NULL) {
        return -1;
    }
    /* Restrict to ISR-safe event kinds only. */
    if (ev->type != TA_EV_ISR_TOUCH && ev->type != TA_EV_ISR_ROTARY) {
        return -1;
    }

    head = m->head;
    tail = m->tail;
    next = (tail + 1u) % TA_ISR_MAIL_CAP;
    if (next == head) {
        m->drops++;
        /* Never block in ISR; prefer drop. */
        fprintf(stderr, "ERROR: ISR mail full\n");
        return -1;
    }
    m->slots[tail] = *ev;
    /* Publish slot before advancing tail. */
    __atomic_store_n(&m->tail, next, __ATOMIC_RELEASE);
    return 0;
}

size_t ta_isr_mail_drain_to_queue(ta_isr_mail_t *m, ta_queue_t *draw_q) {
    size_t n = 0;
    uint32_t head;
    uint32_t tail;

    if (m == NULL || draw_q == NULL) {
        return 0;
    }
    head = m->head;
    tail = __atomic_load_n(&m->tail, __ATOMIC_ACQUIRE);
    while (head != tail) {
        if (ta_queue_push(draw_q, &m->slots[head]) != 0) {
            break;
        }
        head = (head + 1u) % TA_ISR_MAIL_CAP;
        n++;
        __atomic_store_n(&m->head, head, __ATOMIC_RELEASE);
        tail = __atomic_load_n(&m->tail, __ATOMIC_ACQUIRE);
    }
    return n;
}
