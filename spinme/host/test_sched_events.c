/* Host: Scheduler start/stop + fake-time fire with session_id. */
#include "ta_draw_events.h"
#include "ta_event.h"
#include "ta_registry.h"
#include "ta_sched_events.h"

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

static int g_fires;
static ta_session_id_t g_last_session;

static int draw_sink(const ta_event_envelope_t *env) {
    g_fires++;
    g_last_session = env->session_id;
    return 0;
}

int main(void) {
    ta_event_envelope_t env;

    ta_registry_reset();
    ta_sched_reset();
    g_fires = 0;
    ta_sched_start();
    CHECK(ta_registry_register("Draw", draw_sink) == 0);

    ta_env_clear(&env);
    env.event.type = TA_EV_SCHED_START;
    env.session_id = 55;
    CHECK(ta_env_set_src(&env, "Init") == 0);
    CHECK(ta_event_set_sched_start(&env.event, "Draw", TA_EV_DRAW_PAINT, 100,
                                   0) == 0);
    CHECK(ta_registry_post(TA_SCHED_NAME, &env) == 0);

    ta_sched_advance_ms(99);
    CHECK(g_fires == 0);
    ta_sched_advance_ms(1);
    CHECK(g_fires == 1);
    CHECK(g_last_session == 55);
    /* Overdue advances push one event (no catch-up burst). */
    ta_sched_advance_ms(200);
    CHECK(g_fires == 2);

    ta_env_clear(&env);
    env.event.type = TA_EV_SCHED_STOP;
    CHECK(ta_env_set_src(&env, "Init") == 0);
    CHECK(ta_registry_post(TA_SCHED_NAME, &env) == 0);
    ta_sched_advance_ms(500);
    CHECK(g_fires == 2);
    CHECK(ta_sched_now_ms() == 800);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_sched_events: %d checks ok\n", checks);
    return 0;
}
