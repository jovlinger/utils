/* Host: NVM KV copy-out protocol + Config current_controller. */
#include "ta_kv.h"

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
    char buf[32];
    size_t len;
    const char *blob = "MPDController";

    ta_kv_reset();
    CHECK(ta_kv_has("x") == 0);
    CHECK(ta_kv_get_len("x", &len) == TA_KV_MISSING);

    CHECK(ta_kv_put("x", "abc", 3) == TA_KV_OK);
    CHECK(ta_kv_has("x") == 1);
    CHECK(ta_kv_get_len("x", &len) == TA_KV_OK);
    CHECK(len == 3);

    CHECK(ta_kv_get("x", buf, 2, &len) == TA_KV_TOO_SMALL);
    CHECK(len == 3);

    CHECK(ta_kv_get("x", buf, sizeof(buf), &len) == TA_KV_OK);
    CHECK(len == 3);
    CHECK(memcmp(buf, "abc", 3) == 0);

    CHECK(ta_kv_delete("x") == TA_KV_OK);
    CHECK(ta_kv_has("x") == 0);
    CHECK(ta_kv_delete("x") == TA_KV_MISSING);

    CHECK(ta_config_put_controller(blob) == TA_KV_OK);
    CHECK(ta_config_get_controller(buf, sizeof(buf), &len) == TA_KV_OK);
    CHECK(len == strlen(blob));
    CHECK(memcmp(buf, blob, len) == 0);
    CHECK(ta_kv_has(TA_KV_KEY_CONTROLLER) == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_kv: %d checks ok\n", checks);
    return 0;
}
