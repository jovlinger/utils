/* Draw event switch handles ops and async reply_to completions. */
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

static ta_event_envelope_t g_last_reply;
static int g_replies;

static int sink_enqueue(const ta_event_envelope_t *env) {
    g_last_reply = *env;
    g_replies++;
    return 0;
}

int main(void) {
    ta_event_envelope_t env;
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
        ta_env_clear(&env);
        env.event.type = tags[i];
        env.session_id = 3;
        CHECK(ta_env_set_src(&env, "Test") == 0);
        CHECK(ta_registry_post(TA_DRAW_NAME, &env) == 0);
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

    /* Async completion: reply_to on typed update; DONE type implied. */
    ta_env_clear(&env);
    env.event.type = TA_EV_DRAW_UPDATE;
    env.session_id = 99;
    CHECK(ta_env_set_src(&env, "Sched") == 0);
    CHECK(ta_copy_name(env.event.u.draw_update.reply_to, TA_NAME_MAX, "Sched") ==
          0);
    CHECK(ta_registry_post(TA_DRAW_NAME, &env) == 0);
    CHECK(g_replies == 1);
    CHECK(g_last_reply.event.type == TA_EV_DRAW_UPDATE_DONE);
    CHECK(g_last_reply.session_id == 99);
    CHECK(strcmp(g_last_reply.src, TA_DRAW_NAME) == 0);

    ta_env_clear(&env);
    env.event.type = 0x999;
    CHECK(ta_draw_handle(&env) == -1);
    CHECK(ta_draw_stats()->unknown == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_draw_events: %d checks ok\n", checks);
    return 0;
}
