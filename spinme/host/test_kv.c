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

    /* Packed image: head at 0, records linked by little-endian next offsets.
     * 0 means empty/end. Two keys, then a grow-overwrite unlinks the old span.
     */
    {
        const uint8_t *img;
        size_t ilen;
        uint32_t head;
        uint32_t n0;
        uint32_t n1;
        uint16_t k0;
        uint32_t b0;
        int live;

        ta_kv_reset();
        CHECK(ta_kv_put("aa", "hi", 2) == TA_KV_OK);
        CHECK(ta_kv_put("bbb", "xyz", 3) == TA_KV_OK);
        img = ta_kv_image(&ilen);
        CHECK(img != NULL);
        CHECK(ilen > TA_KV_IMAGE_HEAD_SIZE);
        head = (uint32_t)img[0] | ((uint32_t)img[1] << 8) |
               ((uint32_t)img[2] << 16) | ((uint32_t)img[3] << 24);
        CHECK(head == TA_KV_IMAGE_HEAD_SIZE);
        k0 = (uint16_t)(img[head + 4] | (img[head + 5] << 8));
        b0 = (uint32_t)img[head + 6] | ((uint32_t)img[head + 7] << 8) |
             ((uint32_t)img[head + 8] << 16) | ((uint32_t)img[head + 9] << 24);
        CHECK(k0 == 2);
        CHECK(b0 == 2);
        CHECK(memcmp(img + head + TA_KV_REC_HDR_SIZE, "aa", 2) == 0);
        CHECK(memcmp(img + head + TA_KV_REC_HDR_SIZE + 2, "hi", 2) == 0);
        n0 = (uint32_t)img[head] | ((uint32_t)img[head + 1] << 8) |
             ((uint32_t)img[head + 2] << 16) | ((uint32_t)img[head + 3] << 24);
        CHECK(n0 != 0);
        CHECK(memcmp(img + n0 + TA_KV_REC_HDR_SIZE, "bbb", 3) == 0);
        n1 = (uint32_t)img[n0] | ((uint32_t)img[n0 + 1] << 8) |
             ((uint32_t)img[n0 + 2] << 16) | ((uint32_t)img[n0 + 3] << 24);
        CHECK(n1 == 0);

        CHECK(ta_kv_put("aa", "HELLO", 5) == TA_KV_OK);
        CHECK(ta_kv_get("aa", buf, sizeof(buf), &len) == TA_KV_OK);
        CHECK(len == 5);
        CHECK(memcmp(buf, "HELLO", 5) == 0);
        img = ta_kv_image(&ilen);
        head = (uint32_t)img[0] | ((uint32_t)img[1] << 8) |
               ((uint32_t)img[2] << 16) | ((uint32_t)img[3] << 24);
        live = 0;
        while (head != 0) {
            uint16_t kl;
            uint32_t bl;
            uint32_t nxt;

            kl = (uint16_t)(img[head + 4] | (img[head + 5] << 8));
            bl = (uint32_t)img[head + 6] | ((uint32_t)img[head + 7] << 8) |
                 ((uint32_t)img[head + 8] << 16) |
                 ((uint32_t)img[head + 9] << 24);
            if (kl == 2 && memcmp(img + head + TA_KV_REC_HDR_SIZE, "aa", 2) == 0) {
                live++;
                CHECK(bl == 5);
                CHECK(memcmp(img + head + TA_KV_REC_HDR_SIZE + 2, "HELLO", 5) == 0);
            }
            nxt = (uint32_t)img[head] | ((uint32_t)img[head + 1] << 8) |
                  ((uint32_t)img[head + 2] << 16) |
                  ((uint32_t)img[head + 3] << 24);
            head = nxt;
        }
        CHECK(live == 1);
    }

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_kv: %d checks ok\n", checks);
    return 0;
}
