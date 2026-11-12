/* Envelope fields + typed event union round-trip (no sync RPC). */
#include "ta_event.h"
#include "ta_net_events.h"

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

int main(void) {
    ta_event_envelope_t req;
    ta_event_envelope_t reply;
    char prefix[64];

    ta_env_clear(&req);
    CHECK(ta_env_set_src(&req, "Draw") == 0);
    req.session_id = 42;
    req.event.type = TA_EV_NET_POLL;
    CHECK(ta_event_set_net_poll_playerstate(&req.event, "MPDController") == 0);
    CHECK(strcmp(req.src, "Draw") == 0);
    CHECK(strcmp(req.event.u.net_poll_playerstate.reply_to, "MPDController") ==
          0);
    CHECK(req.session_id == 42);

    /* Reply is a separate envelope sharing session_id (not a return value). */
    ta_env_clear(&reply);
    CHECK(ta_env_set_src(&reply, "Net") == 0);
    reply.event.type = TA_EV_NET_POLL_DONE;
    reply.session_id = req.session_id;
    CHECK(reply.session_id == req.session_id);

    CHECK(ta_log_prefix(prefix, sizeof prefix, 1234, 42, "Net") > 0);
    CHECK(strcmp(prefix, "1234|42|Net") == 0);

    /* Oversized name rejected. */
    CHECK(ta_env_set_src(&req, "this_name_is_way_too_long_for_ta") == -1);
    CHECK(ta_event_set_ctrl_set_route(&req.event,
                                      "this_name_is_way_too_long_for_ta") ==
          -1);

    CHECK(ta_now_ms() >= 0u); /* smoke: clock callable */

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_event_envelope: %d checks ok\n", checks);
    return 0;
}
