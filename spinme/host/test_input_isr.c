/* Host: gray-code + velocity; touch/rotary FromISR into Draw mail. */
#include "ta_input_isr.h"
#include "ta_isr_mail.h"
#include "ta_queue.h"

#include <stdio.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                            \
    do {                                                                       \
        checks++;                                                              \
        if (!(cond)) {                                                         \
            failures++;                                                        \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
        }                                                                      \
    } while (0)

int main(void) {
    ta_isr_mail_t mail;
    ta_event_t qstore[8];
    ta_queue_t draw_q;
    ta_event_t ev;

    CHECK(ta_encoder_gray_step(0, 1) == 1);
    CHECK(ta_encoder_gray_step(1, 0) == -1);
    CHECK(ta_encoder_gray_step(0, 3) == 0); /* illegal double bit */
    CHECK(ta_encoder_velocity_steps(200000, 8) == 1);
    CHECK(ta_encoder_velocity_steps(10000, 8) == 8);

    ta_isr_mail_reset(&mail);
    CHECK(ta_queue_init(&draw_q, qstore, 8) == 0);
    CHECK(ta_isr_post_touch(&mail, 120, 80) == 0);
    CHECK(ta_isr_post_rotary(&mail, 2, 0x40) == 0);
    CHECK(ta_isr_mail_drain_to_queue(&mail, &draw_q) == 2);

    ta_queue_peek_wait(&draw_q, &ev);
    CHECK(ev.type == TA_EV_ISR_TOUCH);
    CHECK(ev.payload_len == 4);
    CHECK(ev.payload[0] == 120 && ev.payload[1] == 0);
    CHECK(ev.payload[2] == 80 && ev.payload[3] == 0);
    ta_queue_pop(&draw_q);

    ta_queue_peek_wait(&draw_q, &ev);
    CHECK(ev.type == TA_EV_ISR_ROTARY);
    CHECK((int8_t)ev.payload[0] == 2);
    CHECK(ev.payload[1] == 0x40);
    ta_queue_pop(&draw_q);

    ta_queue_fini(&draw_q);
    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_input_isr: %d checks ok\n", checks);
    return 0;
}
