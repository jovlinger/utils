/* Host: Net POST /event ingress + mDNS advertise stub. */
#include "ta_event.h"
#include "ta_follow_chrome.h"
#include "ta_net_events.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"
#include "ta_router.h"
#include "ta_test_actor.h"
#include "ta_uilayout.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Lightweight glass stubs so get_debug builds without DRAW_CORE. */
int ta_glass_installed(void) { return 0; }
const ta_follow_chrome_t *ta_glass_chrome(void) { return NULL; }
const ta_pack66_t *ta_glass_base_pixels(void) { return NULL; }
void ta_glass_panel_size(uint16_t *out_w, uint16_t *out_h) {
    if (out_w != NULL) {
        *out_w = 0;
    }
    if (out_h != NULL) {
        *out_h = 0;
    }
}
const char *ta_glass_text(uint8_t field) {
    (void)field;
    return "";
}
int ta_glass_polled(void) { return 0; }
int ta_glass_desired(void) { return 0; }
int ta_glass_playing(void) { return 0; }
unsigned ta_glass_page(void) { return 0; }

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

static int g_mode; /* 0=reply 200, 1=no reply (timeout) */

static int actor_enq(const ta_event_envelope_t *env) {
    ta_event_envelope_t reply;

    CHECK(env != NULL);
    CHECK(env->event.type == TA_EV_LOG);
    CHECK(strcmp(env->event.u.log_emit_line.text, "hi") == 0);
    if (g_mode == 1) {
        return 0;
    }
    ta_env_clear(&reply);
    (void)ta_env_set_src(&reply, "Logger");
    reply.session_id = env->session_id;
    reply.event.type = TA_EV_NET_HTTP_REPLY;
    reply.event.u.net_http_reply.http_status = 200;
    reply.event.u.net_http_reply.n = 2;
    reply.event.u.net_http_reply.bytes[0] = 'o';
    reply.event.u.net_http_reply.bytes[1] = 'k';
    ta_net_http_offer_reply(&reply);
    return 0;
}

static size_t build_post(char *dst, size_t cap, const char *path_and_query,
                         const char *body) {
    size_t blen;
    int n;

    blen = body != NULL ? strlen(body) : 0;
    n = snprintf(dst, cap,
                 "POST /event/%s HTTP/1.0\r\nContent-Length: %u\r\n\r\n%s",
                 path_and_query, (unsigned)blen, body != NULL ? body : "");
    if (n < 0 || (size_t)n >= cap) {
        return 0;
    }
    return (size_t)n;
}

int main(void) {
    ta_net_http_response_t resp;
    char req[512];
    size_t n;

    ta_registry_reset();
    ta_net_http_reset();
    ta_net_mdns_reset();
    memset(&resp, 0, sizeof(resp));

    CHECK(ta_registry_register("Logger", actor_enq) == 0);

    g_mode = 0;
    n = build_post(req, sizeof(req), "Logger/LogEmitLine",
                   "severity=3&tag=1&text=hi");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(resp.body_len == 2);
    CHECK(memcmp(resp.body, "ok", 2) == 0);

    /* Query + body merge: body wins on text. */
    n = build_post(req, sizeof(req), "Logger/LogEmitLine?text=no&severity=1",
                   "severity=3&tag=1&text=hi");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);

    n = build_post(req, sizeof(req), "Missing/LogEmitLine", "text=x");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 404);

    g_mode = 1;
    n = build_post(req, sizeof(req), "Logger/LogEmitLine",
                   "severity=1&tag=0&text=hi");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 201);

    CHECK(ta_net_mdns_advertise_count() == 0);
    CHECK(ta_net_mdns_advertise() == 0);
    CHECK(ta_net_mdns_advertise() == 0);
    CHECK(ta_net_mdns_advertise_count() == 2);

    /* Mixed-case path lowercases to canonical test/testrun. */
    ta_test_start();
    n = build_post(req, sizeof(req), "Test/TestRun",
                   "mode=one&selector=smoke");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "status=0") != NULL);
    CHECK(strstr(resp.body, "selector=smoke") != NULL);

    n = build_post(req, sizeof(req), "test/run_test", "mode=0&name=smoke");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);

    n = build_post(req, sizeof(req), "test/get_debug", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "w=") != NULL);
    CHECK(strstr(resp.body, "h=") != NULL);
    CHECK(strstr(resp.body, "fmt=pack66") != NULL);
    CHECK(strstr(resp.body, "logs=") != NULL);
    free(resp.blob);
    resp.blob = NULL;

    n = build_post(req, sizeof(req), "test/list_events", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "list_events") != NULL);
    CHECK(strstr(resp.body, "get_debug") != NULL);

    ta_router_start();
    n = build_post(req, sizeof(req), "controller/list_events", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "debugall") != NULL);
    CHECK(strstr(resp.body, "list_tasks") != NULL);

    n = build_post(req, sizeof(req), "controller/list_tasks", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "controller") != NULL);
    CHECK(strstr(resp.body, "test") != NULL ||
          strstr(resp.body, "Logger") != NULL);
    /* Roster is newline-separated (task list CLI splits lines). */
    CHECK(strchr(resp.body, '\n') != NULL);

    /* Unmapped slug must stay HTTP 400 with this exact body (spinmecli
     * task list surfaces it when the flashed image lacks list_tasks). */
    n = build_post(req, sizeof(req), "controller/not_a_real_event", "");
    CHECK(n > 0);
    CHECK(ta_net_http_handle_request((const uint8_t *)req, n, &resp) == 0);
    CHECK(resp.http_status == 400);
    CHECK(strcmp(resp.body, "unknown event") == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_net_http_event: %d checks ok\n", checks);
    return 0;
}
