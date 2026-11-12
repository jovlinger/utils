/* Dev Test actor: RUN one / suite / timing -> DONE with counts + elapsed. */
#include "ta_event.h"
#include "ta_registry.h"
#include "ta_test_actor.h"

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

static ta_event_envelope_t g_last;
static int g_got;

static int sink(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    g_last = *env;
    g_got++;
    return 0;
}

int main(void) {
    const ta_test_stats_t *st;
    const ta_test_done_t *done;

    ta_registry_reset();
    ta_test_start();
    CHECK(ta_registry_register("Origin", sink) == 0);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_ONE, "smoke", "Origin", 7) == 0);
    CHECK(g_got == 1);
    CHECK(g_last.event.type == TA_EV_TEST_DONE);
    CHECK(g_last.session_id == 7);
    done = &g_last.event.u.test_done;
    CHECK(done->status == 0);
    CHECK(done->n_ran == 1);
    CHECK(done->n_fail == 0);
    CHECK(strcmp(done->selector, "smoke") == 0);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_SUITE, "smoke", "Origin", 8) == 0);
    CHECK(g_got == 1);
    done = &g_last.event.u.test_done;
    CHECK(done->status == 0);
    CHECK(done->n_ran == 1);
    CHECK(done->n_fail == 0);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_TIMING, "smoke", "Origin", 9) == 0);
    CHECK(g_got == 1);
    done = &g_last.event.u.test_done;
    CHECK(done->status == 0);
    CHECK(done->n_ran == 1);
    /* Wall time may be 0 on a fast box; still a filled field. */
    CHECK(done->elapsed_ms < 60000u);

    g_got = 0;
    CHECK(ta_test_post_run(TA_TEST_MODE_ONE, "no_such_test", "Origin", 10) !=
          0);
    CHECK(g_got == 1);
    done = &g_last.event.u.test_done;
    CHECK(done->status != 0);
    CHECK(done->n_fail >= 1);

    st = ta_test_stats();
    CHECK(st->runs >= 4);
    CHECK(st->dones >= 4);

    if (failures) {
        fprintf(stderr, "test_test_actor: %d/%d checks failed\n", failures,
                checks);
        return 1;
    }
    printf("test_test_actor: %d checks ok\n", checks);
    return 0;
}
