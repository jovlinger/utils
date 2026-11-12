#include "ta_isr_mail.h"

#include <stdio.h>
#include <string.h>

void ta_isr_mail_reset(ta_isr_mail_t *m) {
    if (m == NULL) {
        return;
    }
    memset(m, 0, sizeof(*m));
}

int TA_ISR_ATTR ta_isr_mail_push_from_isr(ta_isr_mail_t *m,
                                          const ta_event_envelope_t *env) {
    uint32_t head;
    uint32_t tail;
    uint32_t next;
    const uint8_t *src;
    uint8_t *dst;
    size_t i;

    if (m == NULL || env == NULL) {
        return -1;
    }
    if (env->event.type != TA_EV_ISR_TOUCH &&
        env->event.type != TA_EV_ISR_ROTARY) {
        return -1;
    }

    head = __atomic_load_n(&m->head, __ATOMIC_ACQUIRE);
    tail = m->tail;
    next = (tail + 1u) % TA_ISR_MAIL_CAP;
    if (next == head) {
        m->drops++;
#ifndef SPINME_TA_DEVICE
        fprintf(stderr, "ERROR: ISR mail full\n");
#endif
        return -1;
    }
    src = (const uint8_t *)(const void *)env;
    dst = (uint8_t *)(void *)&m->slots[tail];
    for (i = 0; i < sizeof(ta_event_envelope_t); i++) {
        dst[i] = src[i];
    }
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
