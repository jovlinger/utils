/* Log drain: ACK advances heads; failed send leaves the rings. */
#include "ta_log_accept.h"
#include "ta_log_rings.h"

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
    CHECK(strcmp(url, "tcp://qnap.local:514") == 0);
    if (g_fail) {
        return -1;
    }
    return 0;
}

int main(void) {
    ta_log_accept_reset();
    ta_log_set_url("tcp://qnap.local:514");
    ta_log_set_sender(send_log, NULL);

    /* Failed send leaves buffered lines. */
    g_fail = 1;
    CHECK(ta_log_accept(1, "one") == 0);
    CHECK(ta_log_dump(1000) == 0);
    CHECK(g_sends == 1);
    CHECK(g_last_n == 1);
    CHECK(ta_log_accept_count() == 1);

    /* Success ACKs through and drops heads. */
    g_fail = 0;
    CHECK(ta_log_dump(1001) == 0);
    CHECK(g_sends == 2);
    CHECK(ta_log_accept_count() == 0);
    CHECK(ta_log_last_empty_ms() == 1001);

    CHECK(ta_log_accept(2, "two") == 0);
    CHECK(ta_log_on_empty_tick(1001 + 60 * 1000) == 0);
    CHECK(g_sends == 2);
    CHECK(ta_log_accept_count() == 1);
    CHECK(ta_log_on_empty_tick(1001 + TA_LOG_EMPTY_DUE_MS + 1) == 0);
    CHECK(g_sends == 3);
    CHECK(ta_log_accept_count() == 0);

    /* Cadence KV / short cadence. */
    ta_log_accept_reset();
    ta_log_set_url("tcp://qnap.local:514");
    ta_log_set_sender(send_log, NULL);
    ta_log_set_cadence_s(60);
    g_sends = 0;
    CHECK(ta_log_accept(1, "fast") == 0);
    CHECK(ta_log_dump(0) == 0);
    CHECK(ta_log_accept(2, "again") == 0);
    CHECK(ta_log_on_empty_tick(10 * 1000) == 0);
    CHECK(g_sends == 1);
    CHECK(ta_log_on_empty_tick(60 * 1000) == 0);
    CHECK(g_sends == 2);

    {
        char line[128];
        size_t n;

        n = ta_log_format_syslog(line, sizeof(line), 42, "hello");
        CHECK(n > 0);
        CHECK(strstr(line, "hello") != NULL);
        CHECK(strstr(line, "<14>") == line);
    }

    /* ack_through drops by seq. */
    ta_log_accept_reset();
    CHECK(ta_log_rings_set_caps(512, 512, 1024) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_INFO, 1, "a") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_INFO, 2, "b") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 2);
    CHECK(ta_log_rings_ack_through(1) == 1);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_log_drain: %d checks ok\n", checks);
    return 0;
}
