/* Log accept routes into the three-ring store. */
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

int main(void) {
    const ta_log_accept_event_t *ev;
    char big[TA_LOG_MSG_MAX + 8];

    ta_log_accept_reset();
    CHECK(ta_log_accept(10, "wifi up") == 0);
    CHECK(ta_log_accept(20, "draw paint") == 0);
    CHECK(ta_log_accept_count() == 2);
    ev = ta_log_accept_at(0);
    CHECK(ev != NULL && ev->emit_time_ms == 10);
    CHECK(strcmp(ev->message, "wifi up") == 0);
    CHECK(ta_log_accept(0, "") == -1);
    CHECK(ta_log_accept(0, NULL) == -1);
    memset(big, 'x', sizeof(big) - 1);
    big[sizeof(big) - 1] = '\0';
    CHECK(ta_log_accept(1, big) == -1);
    CHECK(ta_log_accept_rejected() >= 1);

    /* Repeat compress on the INFO ring. */
    CHECK(ta_log_accept(30, "same") == 0);
    CHECK(ta_log_accept(31, "same") == 0);
    CHECK(ta_log_accept_count() == 3);

    /* Level routing. */
    CHECK(ta_log_accept_level(TA_LOG_LEVEL_ERROR, 40, "boom") == 0);
    CHECK(ta_log_accept_level(TA_LOG_LEVEL_WARN, 41, "careful") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) >= 1);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) >= 1);

    /* Dump clears the rings (transitional until ACK drain). */
    CHECK(ta_log_dump(100) == 0);
    CHECK(ta_log_accept_count() == 0);
    CHECK(ta_log_accept(99, "after-dump") == 0);
    CHECK(ta_log_accept_count() == 1);

    ta_log_set_buffer_kb(128);
    CHECK(ta_log_buffer_cap() >= 1000);
    CHECK(ta_log_buffer_cap() <= TA_LOG_ACCEPT_MAX_EVENTS);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_log_accept: %d checks ok\n", checks);
    return 0;
}
