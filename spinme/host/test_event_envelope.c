/* Host tests: async event envelope (no sync RPC). */
#include "ta_event.h"

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
    ta_event_t req;
    ta_event_t reply;
    char prefix[64];
    uint8_t body[4] = {1, 2, 3, 4};

    ta_event_clear(&req);
    CHECK(ta_event_set_src(&req, "Draw") == 0);
    req.type = 100;
    req.session_id = 42;
    CHECK(ta_event_set_reply(&req, "Draw", 101) == 0);
    CHECK(ta_event_set_payload(&req, body, sizeof body) == 0);
    CHECK(strcmp(req.src, "Draw") == 0);
    CHECK(strcmp(req.reply_to, "Draw") == 0);
    CHECK(req.reply_type == 101);
    CHECK(req.session_id == 42);
    CHECK(req.payload_len == 4);

    /* Reply is a separate event sharing session_id (not a return value). */
    ta_event_clear(&reply);
    CHECK(ta_event_set_src(&reply, "Net") == 0);
    reply.type = req.reply_type;
    reply.session_id = req.session_id;
    CHECK(reply.session_id == req.session_id);
    CHECK(reply.type == 101);

    CHECK(ta_log_prefix(prefix, sizeof prefix, 1234, 42, "Net") > 0);
    CHECK(strcmp(prefix, "1234|42|Net") == 0);

    /* Oversized name / payload rejected. */
    CHECK(ta_event_set_src(&req, "this_name_is_way_too_long_for_ta") == -1);
    CHECK(ta_event_set_payload(&req, body, TA_PAYLOAD_MAX + 1) == -1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_event_envelope: %d checks ok\n", checks);
    return 0;
}
