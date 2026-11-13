/* Http TaskActor: register + list_events offer. */
#include "ta_event.h"
#include "ta_http_actor.h"
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
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__,   \
                    #cond);                                                    \
            failures++;                                                        \
        }                                                                      \
    } while (0)

int main(void) {
    ta_event_envelope_t env;
    uint8_t req[256];
    size_t n;
    ta_net_http_response_t resp;

    ta_registry_reset();
    ta_net_http_reset();
    ta_http_reset();
    ta_http_start();
    CHECK(ta_registry_lookup(TA_HTTP_NAME) != NULL);

    ta_env_clear(&env);
    (void)ta_env_set_src(&env, "test");
    env.session_id = 7;
    env.event.type = TA_EV_LIST_EVENTS;
    CHECK(ta_http_enqueue(&env) == 0);

    n = (size_t)snprintf((char *)req, sizeof(req),
                         "POST /event/http/list_events HTTP/1.1\r\n"
                         "Content-Length: 0\r\n\r\n");
    CHECK(ta_net_http_handle_request(req, n, &resp) == 0);
    CHECK(resp.http_status == 200);
    CHECK(strstr(resp.body, "list_events") != NULL);

    ta_http_wifi_up(); /* host no-op */

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_http_actor: %d checks ok\n", checks);
    return 0;
}
