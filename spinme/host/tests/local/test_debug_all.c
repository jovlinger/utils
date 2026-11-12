/* Controller DebugAll fan-out: complete -> HTTP 200, incomplete -> 201. */
#include "ta_event.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"
#include "ta_router.h"

/* ta_debug_status_reply is declared in ta_registry.h */

#include <stdio.h>
#include <stdlib.h>
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

static int g_silent; /* 1 = actor swallows DebugStatus (no reply) */

static int actor_ok(const ta_event_envelope_t *env) {
    if (env == NULL || env->event.type != TA_EV_DEBUG_STATUS) {
        return -1;
    }
    if (g_silent) {
        return 0;
    }
    return ta_debug_status_reply(env, "net", "mdns=0");
}

static int actor_ok2(const ta_event_envelope_t *env) {
    if (env == NULL || env->event.type != TA_EV_DEBUG_STATUS) {
        return -1;
    }
    if (g_silent) {
        return 0;
    }
    return ta_debug_status_reply(env, "draw", "ok");
}

static size_t build_post(char *dst, size_t cap, const char *path,
                         const char *body) {
    size_t blen;
    int n;

    blen = body != NULL ? strlen(body) : 0;
    n = snprintf(dst, cap,
                 "POST /event/%s HTTP/1.0\r\nContent-Length: %u\r\n\r\n%s",
                 path, (unsigned)blen, body != NULL ? body : "");
    if (n < 0 || (size_t)n >= cap) {
        return 0;
    }
    return (size_t)n;
}

int main(void) {
    ta_net_http_response_t resp;
    char req[256];
    size_t n;

    ta_registry_reset();
    ta_router_reset();
    ta_net_http_reset();
    g_silent = 0;
    memset(&resp, 0, sizeof(resp));

    ta_router_start();
    CHECK(ta_registry_register("Net", actor_ok) == 0);
    CHECK(ta_registry_register("Draw", actor_ok2) == 0);

    n = build_post(req, sizeof(req), "controller/debugall", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "net=mdns=0") != NULL);
    CHECK(strstr(resp.body, "draw=ok") != NULL);
    free(resp.blob);
    resp.blob = NULL;

    /* Incomplete: silent actors -> TIMEOUT_SHORT path -> 201. */
    ta_registry_reset();
    ta_router_reset();
    ta_net_http_reset();
    g_silent = 1;
    memset(&resp, 0, sizeof(resp));
    ta_router_start();
    CHECK(ta_registry_register("Net", actor_ok) == 0);
    n = build_post(req, sizeof(req), "Controller/DebugAll", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 201);
    CHECK(TA_TIMEOUT_SHORT_MS == 2000u);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_debug_all: %d checks ok\n", checks);
    return 0;
}
