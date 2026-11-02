/* Rotary/touch payloads posted FromISR into Draw (host + payload layout). */
#ifndef SPINME_TA_INPUT_ISR_H
#define SPINME_TA_INPUT_ISR_H

#include "ta_event.h"
#include "ta_isr_mail.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
/* Touch payload: x u16, y u16 (little-endian in event.payload). */
typedef struct ta_touch_xy {
    uint16_t x;
    uint16_t y;
} ta_touch_xy_t;

/* Rotary payload: steps i8, velocity_q8 u8 (detents/sec scaled). */
typedef struct ta_rotary_step {
    int8_t steps;
    uint8_t velocity_q8;
} ta_rotary_step_t;

/* Gray-code transition filter: prev/cur 2-bit AB; returns -1,0,+1. */
int ta_encoder_gray_step(uint8_t prev_ab, uint8_t cur_ab);

/* Velocity from delta_us between detents: slow=1, flick up to max_step. */
int ta_encoder_velocity_steps(uint32_t delta_us, int max_step);

/* Build + FromISR post touch/rotary into mail (no task mutex). */
int ta_isr_post_touch(ta_isr_mail_t *mail, uint16_t x, uint16_t y);
int ta_isr_post_rotary(ta_isr_mail_t *mail, int8_t steps, uint8_t vel_q8);

#ifdef __cplusplus
}
#endif
#endif
