/* PUT /kv/<key> then exit-all+boot picks up the new actor blob. */
#include "ta_boot.h"
#include "ta_kv.h"
#include "ta_net_kv_http.h"
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

static size_t build_put(char *dst, size_t cap, const char *key,
                        const void *body, size_t n) {
    int hdr;
    hdr = snprintf(dst, cap, "PUT /kv/%s HTTP/1.0\r\nContent-Length: %u\r\n\r\n",
                   key, (unsigned)n);
    if (hdr < 0 || (size_t)hdr + n > cap) {
        return 0;
    }
    memcpy(dst + hdr, body, n);
    return (size_t)hdr + n;
}

int main(void) {
    char req[2048];
    size_t n;
    char blob[16];
    size_t len;
    char big[400];
    char got[400];

    ta_registry_reset();
    ta_kv_install_factory();
    CHECK(ta_boot_from_kv() == 2);

    memset(big, 'L', sizeof(big));
    n = build_put(req, sizeof(req), "Log", big, sizeof(big));
    CHECK(n > 0);
    CHECK(ta_net_kv_http_put((const uint8_t *)req, n) == TA_KV_OK);
    CHECK(ta_kv_get("Log", got, sizeof(got), &len) == TA_KV_OK);
    CHECK(len == sizeof(big));
    CHECK(got[0] == 'L' && got[399] == 'L');

    n = build_put(req, sizeof(req), TA_KV_KEY_ACTORS, "Draw\nNet\nLog\n", 13);
    CHECK(ta_net_kv_http_put((const uint8_t *)req, n) == TA_KV_OK);

    ta_boot_exit_all();
    CHECK(ta_boot_from_kv() == 3);
    CHECK(ta_registry_lookup("Log") != NULL);
    CHECK(ta_kv_get("Log", blob, sizeof(blob), &len) == TA_KV_TOO_SMALL);
    CHECK(len == sizeof(big));
    ta_boot_exit_all();

    CHECK(ta_net_kv_http_put((const uint8_t *)"GET /kv/Log HTTP/1.0\r\n\r\n",
                             24) == TA_KV_BAD_ARG);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_net_kv_http: %d checks ok\n", checks);
    return 0;
}
