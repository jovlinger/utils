/* Host: Log collects until the buffer is full, then rejects. */
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

int main(void) {
    size_t i;
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

    for (i = ta_log_accept_count(); i < TA_LOG_ACCEPT_CAP; i++) {
        CHECK(ta_log_accept((uint32_t)i, "more") == 0);
    }
    /* Filling the buffer dumps immediately, so the next line is kept. */
    CHECK(ta_log_accept_count() == 0);
    CHECK(ta_log_accept(99, "after-dump") == 0);
    CHECK(ta_log_accept_count() == 1);
    CHECK(ta_log_accept_rejected() >= 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_log_accept: %d checks ok\n", checks);
    return 0;
}
