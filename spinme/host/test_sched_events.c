/* Host: Scheduler start/stop + fake-time fire with session_id. */
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

static int draw_sink(const ta_event_t *ev) {
    g_fires++;
    g_last_session = ev->session_id;
    return 0;
}

static void put_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v & 0xff);
    p[1] = (uint8_t)((v >> 8) & 0xff);
    p[2] = (uint8_t)((v >> 16) & 0xff);
    p[3] = (uint8_t)((v >> 24) & 0xff);
}

int main(void) {
    ta_event_t ev;
    uint8_t period[4];

    ta_registry_reset();
    ta_sched_reset();
    g_fires = 0;
    ta_sched_start();
    CHECK(ta_registry_register("Draw", draw_sink) == 0);

    put_u32(period, 100);
    ta_event_clear(&ev);
    ev.type = TA_EV_SCHED_START;
    ev.session_id = 55;
    CHECK(ta_event_set_src(&ev, "Init") == 0);
    CHECK(ta_event_set_reply(&ev, "Draw", 0x201) == 0); /* paint-ish */
    CHECK(ta_event_set_payload(&ev, period, 4) == 0);
    CHECK(ta_registry_post(TA_SCHED_NAME, &ev) == 0);

    ta_sched_advance_ms(99);
    CHECK(g_fires == 0);
    ta_sched_advance_ms(1);
    CHECK(g_fires == 1);
    CHECK(g_last_session == 55);
    /* Overdue advances push one event (no catch-up burst). */
    ta_sched_advance_ms(200);
    CHECK(g_fires == 2);

    ta_event_clear(&ev);
    ev.type = TA_EV_SCHED_STOP;
    CHECK(ta_event_set_src(&ev, "Init") == 0);
    CHECK(ta_registry_post(TA_SCHED_NAME, &ev) == 0);
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
