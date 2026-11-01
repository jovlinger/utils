/* Host: clock 1Hz, scroll ox, one-offs; fake-time. */
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

static int g_updates;
static int g_scrolls;
static int16_t g_last_ox;
static int g_oneshot;

static int draw_sink(const ta_event_t *ev) {
    if (ev->type == TA_EV_DRAW_UPDATE) {
        g_updates++;
    } else if (ev->type == TA_EV_DRAW_SCROLL_OX) {
        g_scrolls++;
        if (ev->payload_len >= 2) {
            g_last_ox = (int16_t)(ev->payload[0] | (ev->payload[1] << 8));
        }
    } else if (ev->type == TA_EV_DRAW_PAINT) {
        g_oneshot++;
    }
    return 0;
}

int main(void) {
    ta_registry_reset();
    ta_sched_reset();
    g_updates = g_scrolls = g_oneshot = 0;
    ta_sched_start();
    CHECK(ta_registry_register(TA_DRAW_NAME, draw_sink) == 0);

    CHECK(ta_sched_arm_clock_1hz(TA_DRAW_NAME, 1) == 0);
    CHECK(ta_sched_arm_scroll(TA_DRAW_NAME, 1, 50) == 0);
    CHECK(ta_sched_arm_oneshot(TA_DRAW_NAME, 1, 30, TA_EV_DRAW_PAINT) == 0);

    ta_sched_advance_ms(29);
    CHECK(g_oneshot == 0);
    ta_sched_advance_ms(1);
    CHECK(g_oneshot == 1);
    ta_sched_advance_ms(100);
    CHECK(g_oneshot == 1); /* one-shot does not repeat */

    ta_sched_advance_ms(870); /* total 1000 */
    CHECK(g_updates == 1);
    CHECK(g_scrolls >= 1);
    CHECK(g_last_ox >= 1);

    ta_sched_advance_ms(1000);
    CHECK(g_updates == 2);
    CHECK(ta_sched_stats()->clock_fires == 2);
    CHECK(ta_sched_stats()->oneshots_fired == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_sched_cadence: %d checks ok\n", checks);
    return 0;
}
