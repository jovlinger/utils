/* Log init KV-gets log_receiver_url; inform installs the drain URL. */
#include "ta_all.h"
#include "ta_kv.h"
#include "ta_kv_actor.h"
#include "ta_log_accept.h"
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

static char g_url[128];

static int send_log(const char *url, const ta_log_accept_event_t *rows,
                    size_t n, void *ud) {
    (void)rows;
    (void)n;
    (void)ud;
    snprintf(g_url, sizeof(g_url), "%s", url);
    return 0;
}

static int enq_log(const ta_event_envelope_t *env) {
    return ta_log_handle_envelope(env);
}

int main(void) {
    const char *url = "tcp://gmk.local:9000";

    ta_kv_reset();
    ta_registry_reset();
    ta_log_accept_reset();
    CHECK(ta_kv_actor_set(TA_KV_KEY_LOG_URL, url, strlen(url)) == 0);
    CHECK(ta_registry_register("Log", enq_log) == 0);
    ta_log_set_sender(send_log, NULL);
    CHECK(ta_all_broadcast_perform_init("Init") == 1);
    CHECK(ta_log_accept(5, "booted") == 0);
    CHECK(ta_log_dump(10) == 0);
    CHECK(strcmp(g_url, url) == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_log_init: %d checks ok\n", checks);
    return 0;
}
