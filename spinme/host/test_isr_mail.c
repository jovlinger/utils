/* Host: FromISR path without task mutex; drain into Draw queue. */
#include "ta_event.h"
#include "ta_isr_mail.h"
#include "ta_queue.h"

#include <pthread.h>
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

static ta_isr_mail_t mail;
static ta_event_envelope_t qstore[16];
static ta_queue_t draw_q;

static void *fake_isr(void *arg) {
    ta_event_envelope_t env;
    int i;

    (void)arg;
    for (i = 0; i < 3; i++) {
        ta_env_clear(&env);
        env.event.type = TA_EV_ISR_TOUCH;
        CHECK(ta_env_set_src(&env, "ISR") == 0);
        env.session_id = (ta_session_id_t)(10 + i);
        CHECK(ta_isr_mail_push_from_isr(&mail, &env) == 0);
    }
    return NULL;
}

int main(void) {
    pthread_t th;
    ta_event_envelope_t env;
    int i;

    ta_isr_mail_reset(&mail);
    CHECK(ta_queue_init(&draw_q, qstore, 16) == 0);

    /* Reject non-ISR types (would imply paint/net in ISR). */
    ta_env_clear(&env);
    env.event.type = TA_EV_LOG;
    CHECK(ta_env_set_src(&env, "ISR") == 0);
    CHECK(ta_isr_mail_push_from_isr(&mail, &env) == -1);

    CHECK(pthread_create(&th, NULL, fake_isr, NULL) == 0);
    pthread_join(th, NULL);

    CHECK(ta_isr_mail_drain_to_queue(&mail, &draw_q) == 3);
    for (i = 0; i < 3; i++) {
        ta_queue_peek_wait(&draw_q, &env);
        CHECK(env.event.type == TA_EV_ISR_TOUCH);
        CHECK(env.session_id == (ta_session_id_t)(10 + i));
        ta_queue_pop(&draw_q);
    }

    /* Fill ISR mail then drop. */
    for (i = 0; i < TA_ISR_MAIL_CAP - 1; i++) {
        ta_env_clear(&env);
        env.event.type = TA_EV_ISR_ROTARY;
        CHECK(ta_env_set_src(&env, "ISR") == 0);
        CHECK(ta_isr_mail_push_from_isr(&mail, &env) == 0);
    }
    CHECK(ta_isr_mail_push_from_isr(&mail, &env) == -1);
    CHECK(mail.drops == 1);

    ta_queue_fini(&draw_q);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_isr_mail: %d checks ok\n", checks);
    return 0;
}
