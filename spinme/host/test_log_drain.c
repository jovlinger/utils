/* Host: drain sends, clears on 502, and skips ticks inside 4:30. */
#include "ta_log_accept.h"

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

static int g_sends;
static int g_fail;
static size_t g_last_n;

static int send_log(const char *url, const ta_log_accept_event_t *rows,
                    size_t n, void *ud) {
    (void)rows;
    (void)ud;
    g_sends++;
    g_last_n = n;
    CHECK(strcmp(url, "tcp://gmk.local:9000") == 0);
    if (g_fail) {
        return -1;
    }
    return 0;
}

int main(void) {
    ta_log_accept_reset();
    ta_log_set_url("tcp://gmk.local:9000");
    ta_log_set_sender(send_log, NULL);
    g_fail = 1;
    CHECK(ta_log_accept(1, "one") == 0);
    CHECK(ta_log_dump(1000) == 0);
    CHECK(g_sends == 1);
    CHECK(g_last_n == 1);
    CHECK(ta_log_accept_count() == 0);
    CHECK(ta_log_last_empty_ms() == 1000);

    CHECK(ta_log_accept(2, "two") == 0);
    CHECK(ta_log_on_empty_tick(1000 + 60 * 1000) == 0);
    CHECK(g_sends == 1);
    CHECK(ta_log_accept_count() == 1);
    CHECK(ta_log_on_empty_tick(1000 + TA_LOG_EMPTY_DUE_MS + 1) == 0);
    CHECK(g_sends == 2);
    CHECK(ta_log_accept_count() == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_log_drain: %d checks ok\n", checks);
    return 0;
}
