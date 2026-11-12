/* Broadcast perform_init delivers once to every registered actor. */
#include "ta_all.h"
#include "ta_event.h"
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

static int g_draw;
static int g_net;
static int g_log;

static int count_init(int *slot, const ta_event_envelope_t *env) {
    if (env->event.type == TA_EV_ALL_PERFORM_INIT) {
        (*slot)++;
    }
    return 0;
}

static int enq_draw(const ta_event_envelope_t *env) {
    return count_init(&g_draw, env);
}
static int enq_net(const ta_event_envelope_t *env) {
    return count_init(&g_net, env);
}
static int enq_log(const ta_event_envelope_t *env) {
    return count_init(&g_log, env);
}

int main(void) {
    ta_event_t ev;
    const char *blob = "http://gmk.local:9";

    ta_registry_reset();
    CHECK(ta_registry_register("Draw", enq_draw) == 0);
    CHECK(ta_registry_register("Net", enq_net) == 0);
    CHECK(ta_registry_register("Log", enq_log) == 0);
    CHECK(ta_all_broadcast_perform_init("Init") == 3);
    CHECK(g_draw == 1);
    CHECK(g_net == 1);
    CHECK(g_log == 1);
    CHECK(ta_all_broadcast_perform_init("Init") == 3);
    CHECK(g_draw == 2 && g_net == 2 && g_log == 2);

    CHECK(ta_event_set_all_inform_result(&ev, 0, "log_receiver_url", blob,
                                         strlen(blob)) == 0);
    CHECK(ev.type == TA_EV_ALL_INFORM_RESULT);
    CHECK(ev.u.all_inform_result.status == 0);
    CHECK(ev.u.all_inform_result.n == strlen(blob));
    CHECK(memcmp(ev.u.all_inform_result.bytes, blob, strlen(blob)) == 0);
    CHECK(strcmp(ev.u.all_inform_result.key, "log_receiver_url") == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_all_init: %d checks ok\n", checks);
    return 0;
}
