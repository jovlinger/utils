/* Test actor: PC forks build/test_*; device runs built-in probes; HTTP replies. */
#ifndef SPINME_TA_TEST_ACTOR_H
#define SPINME_TA_TEST_ACTOR_H

#include "ta_event.h"

#ifdef __cplusplus
extern "C" {
#endif

#define TA_TEST_NAME "test"

typedef struct ta_test_stats {
    unsigned handled;
    unsigned unknown;
    unsigned runs;
    unsigned dones;
} ta_test_stats_t;

void ta_test_reset(void);
void ta_test_start(void);
int ta_test_enqueue(const ta_event_envelope_t *env);
int ta_test_handle(const ta_event_envelope_t *env);
const ta_test_stats_t *ta_test_stats(void);

/* Post TA_EV_TEST_RUN to Test. selector is a short name (smoke) or suite. */
int ta_test_post_run(uint8_t mode, const char *selector, const char *reply_to,
                     ta_session_id_t session);

#ifdef __cplusplus
}
#endif
#endif
