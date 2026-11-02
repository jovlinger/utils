#include "ta_input_isr.h"

#include <string.h>

/* Classic quadrature: valid single-bit transitions. */
int ta_encoder_gray_step(uint8_t prev_ab, uint8_t cur_ab) {
    static const int8_t table[4][4] = {
        /* to:  0   1   2   3 */
        /*0*/ {0, 1, -1, 0},
        /*1*/ {-1, 0, 0, 1},
        /*2*/ {1, 0, 0, -1},
        /*3*/ {0, -1, 1, 0},
    };
    prev_ab &= 3u;
    cur_ab &= 3u;
    return (int)table[prev_ab][cur_ab];
}

int ta_encoder_velocity_steps(uint32_t delta_us, int max_step) {
    int step;

    if (max_step < 1) {
        max_step = 1;
    }
    if (delta_us == 0 || delta_us > 200000u) {
        return 1;
    }
    /* Map ~200ms -> 1, ~10ms -> max_step. */
    if (delta_us >= 100000u) {
        return 1;
    }
    step = (int)(100000u / delta_us);
    if (step < 1) {
        step = 1;
    }
    if (step > max_step) {
        step = max_step;
    }
    return step;
}

/* ISR-context envelope fill: byte loops only, no flash-resident helpers. */
static void TA_ISR_ATTR isr_event_init(ta_event_t *ev, ta_event_type_t type) {
    uint8_t *p = (uint8_t *)(void *)ev;
    size_t i;

    for (i = 0; i < sizeof(*ev); i++) {
        p[i] = 0;
    }
    ev->type = type;
    ev->src[0] = 'I';
    ev->src[1] = 'S';
    ev->src[2] = 'R';
    ev->src[3] = '\0';
}

int TA_ISR_ATTR ta_isr_post_touch(ta_isr_mail_t *mail, uint16_t x,
                                  uint16_t y) {
    ta_event_t ev;

    isr_event_init(&ev, TA_EV_ISR_TOUCH);
    ev.payload[0] = (uint8_t)(x & 0xff);
    ev.payload[1] = (uint8_t)((x >> 8) & 0xff);
    ev.payload[2] = (uint8_t)(y & 0xff);
    ev.payload[3] = (uint8_t)((y >> 8) & 0xff);
    ev.payload_len = 4;
    return ta_isr_mail_push_from_isr(mail, &ev);
}

int TA_ISR_ATTR ta_isr_post_rotary(ta_isr_mail_t *mail, int8_t steps,
                                   uint8_t vel_q8) {
    ta_event_t ev;

    isr_event_init(&ev, TA_EV_ISR_ROTARY);
    ev.payload[0] = (uint8_t)steps;
    ev.payload[1] = vel_q8;
    ev.payload_len = 2;
    return ta_isr_mail_push_from_isr(mail, &ev);
}
