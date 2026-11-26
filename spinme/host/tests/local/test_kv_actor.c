/* KvConfig TaskActor: wrappers + get/set/list/delete via HTTP offer. */
#include "ta_event.h"
#include "ta_kv.h"
#include "ta_kv_actor.h"
#include "ta_net_http_event.h"
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

static size_t build_post(char *dst, size_t cap, const char *path,
                         const char *body) {
    return (size_t)snprintf(dst, cap,
                            "POST /event/%s HTTP/1.1\r\n"
                            "Host: t\r\n"
                            "Content-Type: application/x-www-form-urlencoded\r\n"
                            "Content-Length: %zu\r\n"
                            "\r\n"
                            "%s",
                            path, strlen(body), body);
}

int main(void) {
    const char *url = "tcp://gmk.local:9000";
    ta_net_http_response_t resp;
    char req[512];
    size_t n;

    ta_kv_reset();
    ta_registry_reset();
    ta_net_http_reset();
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

    /* KvConfig actor via HTTP. */
    ta_kv_reset();
    ta_registry_reset();
    ta_net_http_reset();
    ta_kvconfig_start();

    n = build_post(req, sizeof(req), "kvconfig/kvset",
                   "key=flag&type=0&value=1");
    memset(&resp, 0, sizeof(resp));
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "ok") != NULL);

    n = build_post(req, sizeof(req), "kvconfig/kvget", "key=flag");
    memset(&resp, 0, sizeof(resp));
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "type=0") != NULL);

    n = build_post(req, sizeof(req), "kvconfig/kvset",
                   "key=name&type=2&value=hello");
    memset(&resp, 0, sizeof(resp));
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);

    n = build_post(req, sizeof(req), "kvconfig/kvlist", "");
    memset(&resp, 0, sizeof(resp));
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "flag") != NULL);
    CHECK(strstr(resp.body, "name") != NULL);

    n = build_post(req, sizeof(req), "kvconfig/kvdelete", "key=flag");
    memset(&resp, 0, sizeof(resp));
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);

    n = build_post(req, sizeof(req), "kvconfig/kvget", "key=flag");
    memset(&resp, 0, sizeof(resp));
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 404);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_kv_actor: %d checks ok\n", checks);
    return 0;
}
