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

    /* Factory image is writable: overwrite, then reload the snapshot. */
    {
        uint8_t snap[4096];
        size_t slen;
        const uint8_t *img;
        char got[32];

        ta_kv_install_factory();
        CHECK(ta_kv_get(TA_KV_KEY_ACTORS, got, sizeof(got), &len) == TA_KV_OK);
        CHECK(len == 9);
        CHECK(memcmp(got, "Draw\nNet\n", 9) == 0);
        img = ta_kv_image(&slen);
        CHECK(slen <= sizeof(snap));
        memcpy(snap, img, slen);
        CHECK(ta_kv_put(TA_KV_KEY_ACTORS, "Draw\n", 5) == TA_KV_OK);
        CHECK(ta_kv_get(TA_KV_KEY_ACTORS, got, sizeof(got), &len) == TA_KV_OK);
        CHECK(len == 5);
        CHECK(ta_kv_load_image(snap, slen) == TA_KV_OK);
        CHECK(ta_kv_get(TA_KV_KEY_ACTORS, got, sizeof(got), &len) == TA_KV_OK);
        CHECK(memcmp(got, "Draw\nNet\n", 9) == 0);
        CHECK(ta_kv_get("Draw", got, sizeof(got), &len) == TA_KV_OK);
        CHECK(memcmp(got, "draw-v1", 7) == 0);
        CHECK(ta_kv_load_image(snap, 2) == TA_KV_BAD_ARG);
    }

    /* First-fit reuses a deleted hole, a shrink leftover, and the tail. */
    {
        const uint8_t *img;
        size_t ilen;
        size_t hw_after_two;
        uint32_t head;
        uint32_t at_c;
        char got[32];

        ta_kv_reset();
        CHECK(ta_kv_put("a", "AAAAAAAA", 8) == TA_KV_OK);
        CHECK(ta_kv_put("b", "BBBBBBBB", 8) == TA_KV_OK);
        img = ta_kv_image(&ilen);
        hw_after_two = ilen;
        CHECK(ta_kv_delete("a") == TA_KV_OK);
        CHECK(ta_kv_put("c", "CCCCCCCC", 8) == TA_KV_OK);
        img = ta_kv_image(&ilen);
        CHECK(ilen == hw_after_two);
        head = (uint32_t)img[0] | ((uint32_t)img[1] << 8) |
               ((uint32_t)img[2] << 16) | ((uint32_t)img[3] << 24);
        at_c = 0;
        while (head != 0) {
            uint16_t kl;

            kl = (uint16_t)(img[head + 4] | (img[head + 5] << 8));
            if (kl == 1 && img[head + TA_KV_REC_HDR_SIZE] == 'c') {
                at_c = head;
            }
            head = (uint32_t)img[head] | ((uint32_t)img[head + 1] << 8) |
                   ((uint32_t)img[head + 2] << 16) |
                   ((uint32_t)img[head + 3] << 24);
        }
        CHECK(at_c == TA_KV_IMAGE_HEAD_SIZE);
        CHECK(ta_kv_put("a", "AAAAAAAA", 8) == TA_KV_OK);
        img = ta_kv_image(&ilen);
        CHECK(ilen > hw_after_two);
        CHECK(ta_kv_get("a", got, sizeof(got), &len) == TA_KV_OK);
        CHECK(ta_kv_get("b", got, sizeof(got), &len) == TA_KV_OK);
        CHECK(ta_kv_get("c", got, sizeof(got), &len) == TA_KV_OK);

        ta_kv_reset();
        CHECK(ta_kv_put("a", "0123456789abcdef", 16) == TA_KV_OK);
        CHECK(ta_kv_put("b", "bbbb", 4) == TA_KV_OK);
        img = ta_kv_image(&ilen);
        hw_after_two = ilen;
        CHECK(ta_kv_put("a", "tiny", 4) == TA_KV_OK);
        CHECK(ta_kv_put("z", "Z", 1) == TA_KV_OK);
        img = ta_kv_image(&ilen);
        CHECK(ilen == hw_after_two);
        CHECK(ta_kv_get("z", got, sizeof(got), &len) == TA_KV_OK);
        CHECK(len == 1);
    }

    {
        static const char *const names[] = {"Draw", "Net"};
        char name[32];
        char blob[32];

        ta_kv_reset();
        CHECK(ta_kv_set_roster(names, 2) == TA_KV_OK);
        CHECK(ta_kv_roster_count() == 2);
        CHECK(ta_kv_roster_at(0, name, sizeof(name), &len) == TA_KV_OK);
        CHECK(len == 4);
        CHECK(memcmp(name, "Draw", 4) == 0);
        CHECK(ta_kv_roster_at(1, name, sizeof(name), &len) == TA_KV_OK);
        CHECK(memcmp(name, "Net", 3) == 0);
        CHECK(ta_kv_put("Draw", "draw-v1", 7) == TA_KV_OK);
        CHECK(ta_kv_put("Net", "net-v1", 6) == TA_KV_OK);
        CHECK(ta_kv_roster_at(0, name, sizeof(name), &len) == TA_KV_OK);
        name[len] = '\0';
        CHECK(ta_kv_get(name, blob, sizeof(blob), &len) == TA_KV_OK);
        CHECK(memcmp(blob, "draw-v1", 7) == 0);
        CHECK(ta_kv_roster_at(2, name, sizeof(name), &len) == TA_KV_MISSING);
        ta_kv_install_factory();
        CHECK(ta_kv_roster_count() == 2);
    }

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_kv: %d checks ok\n", checks);
    return 0;
}
