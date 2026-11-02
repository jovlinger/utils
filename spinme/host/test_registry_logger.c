/* Host: Init entry list starts Logger; registry post; log policies. */
#include "ta_event.h"
#include "ta_init.h"
#include "ta_logger.h"
#include "ta_registry.h"

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

static int g_other_started;

static int other_enqueue(const ta_event_envelope_t *env) {
    (void)env;
    return 0;
}

static void start_other(void) {
    g_other_started = 1;
    CHECK(ta_registry_register("Other", other_enqueue) == 0);
}

int main(void) {
    const ta_log_stats_t *st;

    ta_registry_reset();
    ta_logger_reset();
    ta_init_reset();

    CHECK(ta_init_add_entry(TA_LOGGER_NAME, ta_logger_start) == 0);
    CHECK(ta_init_add_entry("Other", start_other) == 0);
    CHECK(ta_init_entry_count() == 2);

    ta_init_run_entries();
    CHECK(g_other_started == 1);
    CHECK(ta_registry_lookup(TA_LOGGER_NAME) != NULL);
    CHECK(ta_registry_lookup("Other") != NULL);
    CHECK(ta_registry_lookup("Missing") == NULL);

    ta_logger_set_policy(0, TA_LOG_POLICY_DROP);
    ta_logger_set_policy(1, TA_LOG_POLICY_NVM);
    ta_logger_set_policy(2, TA_LOG_POLICY_EXTERNAL);

    CHECK(ta_logger_emit(9, "Draw", 0, 0, "quiet") == 0);
    CHECK(ta_logger_emit(9, "Draw", 1, 0, "keep") == 0);
    CHECK(ta_logger_emit(9, "Net", 2, 0, "wire") == 0);
    CHECK(ta_logger_drain(8) == 3);

    st = ta_logger_stats();
    CHECK(st->accepted == 3);
    CHECK(st->dropped == 1);
    CHECK(st->nvm == 1);
    CHECK(st->external == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_registry_logger: %d checks ok\n", checks);
    return 0;
}
