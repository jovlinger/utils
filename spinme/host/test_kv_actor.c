/* Host: KV set then get replies to the caller with ta_all_inform_result. */
#include "ta_kv.h"
#include "ta_kv_actor.h"
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

static int g_got;
static uint8_t g_status;
static char g_key[TA_ALL_KEY_MAX];
static char g_bytes[TA_ALL_INFORM_MAX];
static uint16_t g_n;

static int enq_log(const ta_event_envelope_t *env) {
    if (env->event.type != TA_EV_ALL_INFORM_RESULT) {
        return 0;
    }
    g_got++;
    g_status = env->event.u.all_inform_result.status;
    g_n = env->event.u.all_inform_result.n;
    memcpy(g_key, env->event.u.all_inform_result.key, TA_ALL_KEY_MAX);
    if (g_n > 0 && g_n <= TA_ALL_INFORM_MAX) {
        memcpy(g_bytes, env->event.u.all_inform_result.bytes, g_n);
    }
    return 0;
}

int main(void) {
    const char *url = "tcp://gmk.local:9000";

    ta_kv_reset();
    ta_registry_reset();
    CHECK(ta_registry_register("Log", enq_log) == 0);
    CHECK(ta_kv_actor_set(TA_KV_KEY_LOG_URL, url, strlen(url)) == 0);
    CHECK(ta_kv_actor_get("Log", TA_KV_KEY_LOG_URL) == 0);
    CHECK(g_got == 1);
    CHECK(g_status == TA_KV_OK);
    CHECK(strcmp(g_key, TA_KV_KEY_LOG_URL) == 0);
    CHECK(g_n == strlen(url));
    CHECK(memcmp(g_bytes, url, strlen(url)) == 0);

    g_got = 0;
    CHECK(ta_kv_actor_get("Log", "missing-key") == 0);
    CHECK(g_got == 1);
    CHECK(g_status == TA_KV_MISSING);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_kv_actor: %d checks ok\n", checks);
    return 0;
}
