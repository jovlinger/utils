/* Host: Draw event enum switch + async reply_to completion. */
#include "ta_draw_events.h"
#include "ta_event.h"
#include "ta_registry.h"

#include <stddef.h>
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

static ta_event_t g_last_reply;
static int g_replies;

static int sink_enqueue(const ta_event_t *ev) {
    g_last_reply = *ev;
    g_replies++;
    return 0;
}

int main(void) {
    ta_event_t ev;
    const ta_draw_stats_t *st;
    const ta_event_type_t tags[] = {
        TA_EV_DRAW_UPDATE,         TA_EV_DRAW_PAINT,   TA_EV_DRAW_REACT_TOUCH,
        TA_EV_DRAW_REACT_ROTATE, TA_EV_DRAW_SET_SHAPE_STACK, TA_EV_DRAW_LOG};

    ta_registry_reset();
    ta_draw_reset();
    g_replies = 0;
    ta_draw_start();
    CHECK(ta_registry_register("Sched", sink_enqueue) == 0);

    /* Switch covers every documented tag. */
    for (size_t i = 0; i < sizeof(tags) / sizeof(tags[0]); i++) {
        ta_event_clear(&ev);
        ev.type = tags[i];
        ev.session_id = 3;
        CHECK(ta_event_set_src(&ev, "Test") == 0);
        CHECK(ta_registry_post(TA_DRAW_NAME, &ev) == 0);
    }
    st = ta_draw_stats();
    CHECK(st->handled == 6);
    CHECK(st->update == 1);
    CHECK(st->paint == 1);
    CHECK(st->touch == 1);
    CHECK(st->rotate == 1);
    CHECK(st->set_stack == 1);
    CHECK(st->log == 1);
    CHECK(st->unknown == 0);

    /* Async completion: reply_to + reply_type path via DONE type. */
    ta_event_clear(&ev);
    ev.type = TA_EV_DRAW_UPDATE;
    ev.session_id = 99;
    CHECK(ta_event_set_src(&ev, "Sched") == 0);
    CHECK(ta_event_set_reply(&ev, "Sched", TA_EV_DRAW_UPDATE_DONE) == 0);
    CHECK(ta_registry_post(TA_DRAW_NAME, &ev) == 0);
    CHECK(g_replies == 1);
    CHECK(g_last_reply.type == TA_EV_DRAW_UPDATE_DONE);
    CHECK(g_last_reply.session_id == 99);
    CHECK(strcmp(g_last_reply.src, TA_DRAW_NAME) == 0);

    ta_event_clear(&ev);
    ev.type = 0x999;
    CHECK(ta_draw_handle(&ev) == -1);
    CHECK(ta_draw_stats()->unknown == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_draw_events: %d checks ok\n", checks);
    return 0;
}
