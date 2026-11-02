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

int ta_isr_post_touch(ta_isr_mail_t *mail, uint16_t x, uint16_t y) {
    ta_event_t ev;
    uint8_t pl[4];

    ta_event_clear(&ev);
    ev.type = TA_EV_ISR_TOUCH;
    (void)ta_event_set_src(&ev, "ISR");
    pl[0] = (uint8_t)(x & 0xff);
    pl[1] = (uint8_t)((x >> 8) & 0xff);
    pl[2] = (uint8_t)(y & 0xff);
    pl[3] = (uint8_t)((y >> 8) & 0xff);
    if (ta_event_set_payload(&ev, pl, 4) != 0) {
        return -1;
    }
    return ta_isr_mail_push_from_isr(mail, &ev);
}

int ta_isr_post_rotary(ta_isr_mail_t *mail, int8_t steps, uint8_t vel_q8) {
    ta_event_t ev;
    uint8_t pl[2];

    ta_event_clear(&ev);
    ev.type = TA_EV_ISR_ROTARY;
    (void)ta_event_set_src(&ev, "ISR");
    pl[0] = (uint8_t)steps;
    pl[1] = vel_q8;
    if (ta_event_set_payload(&ev, pl, 2) != 0) {
        return -1;
    }
    return ta_isr_mail_push_from_isr(mail, &ev);
}
