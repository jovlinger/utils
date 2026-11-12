/* Three-ring log store: levels, repeat compress, overrun, merge, caps. */
#include "ta_log_rings.h"

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

static void fill11(char *dst, char tag, char nibble) {
    memcpy(dst, "X-message-X", 12);
    dst[0] = tag;
    dst[10] = nibble;
}

static void test_levels(void) {
    ta_log_rings_entry_t ent;

    CHECK(ta_log_rings_set_caps(4096, 4096, 4096) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 1, "boom") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 2, "careful") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_INFO, 3, "note") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_DEBUG, 4, "dbg") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_VERBOSE, 5, "verb") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_NONE, 6, "none") == 0);

    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 1u);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 4u);

    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_ERROR);
    CHECK(ent.ring == TA_LOG_RING_ERROR);
    CHECK(ent.repeat == 1u);
    CHECK(ent.time_ms == 1u);
    CHECK(strcmp(ent.text, "boom") == 0);

    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 0, &ent) == 0);
    CHECK(strcmp(ent.text, "careful") == 0);
    CHECK(ent.level == TA_LOG_LEVEL_WARN);

    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 0, &ent) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_INFO);
    CHECK(strcmp(ent.text, "note") == 0);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 1, &ent) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_DEBUG);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 2, &ent) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_VERBOSE);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 3, &ent) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_NONE);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 4, &ent) != 0);

    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 7, NULL) != 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 7, "") != 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 1u);
}

static void test_repeat(void) {
    ta_log_rings_entry_t ent;
    ta_log_rings_iter_t it;
    int rows;

    CHECK(ta_log_rings_set_caps(4096, 4096, 4096) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 10, "same") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 50, "same") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(ent.repeat == 2u);
    CHECK(ent.time_ms == 50u);
    CHECK(strcmp(ent.text, "same") == 0);

    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 60, "other") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 2u);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 1, &ent) == 0);
    CHECK(ent.repeat == 1u);
    CHECK(strcmp(ent.text, "other") == 0);

    /* Same text on another ring is a different line. */
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 70, "same") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 2u);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(ent.repeat == 2u);

    memset(&it, 0, sizeof(it));
    CHECK(ta_log_rings_iter_begin(&it) == 0);
    rows = 0;
    while (ta_log_rings_iter_next(&it, &ent)) {
        rows++;
        if (strcmp(ent.text, "same") == 0 && ent.ring == TA_LOG_RING_ERROR) {
            CHECK(ent.repeat == 2u);
            CHECK(ent.time_ms == 50u);
        }
    }
    CHECK(rows == 3);
    ta_log_rings_iter_end(&it);
}

static void test_overrun_drop_head(void) {
    ta_log_rings_entry_t ent;
    uint32_t nb;
    char a[12];
    char b[12];
    char c[12];
    char d[12];

    nb = ta_log_rings_node_bytes(11);
    CHECK(nb != 0u);
    CHECK(ta_log_rings_set_caps(nb * 2u, 8192, 8192) == 0);
    fill11(a, 'E', '1');
    fill11(b, 'E', '2');
    fill11(c, 'E', '3');
    fill11(d, 'E', '4');
    CHECK(strlen(a) == 11u);

    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 1, a) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 2, b) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 2u);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 3, c) == 0);

    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 2u);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(strcmp(ent.text, b) == 0);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 1, &ent) == 0);
    CHECK(strcmp(ent.text, c) == 0);
    CHECK(ent.time_ms == 3u);

    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 0, &ent) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_WARN);
    CHECK(ent.repeat == 1u);
    CHECK(strcmp(ent.text, TA_LOG_RINGS_OVERRUN_TEXT) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 0u);

    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 4, d) == 0);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(strcmp(ent.text, c) == 0);
    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 0, &ent) == 0);
    CHECK(ent.repeat == 2u);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
}

static void test_overrun_drops_until_fit(void) {
    ta_log_rings_entry_t ent;
    uint32_t small;
    uint32_t big;
    char wide[48];

    small = ta_log_rings_node_bytes(1);
    big = ta_log_rings_node_bytes(47);
    CHECK(big == small * 2u);
    CHECK(ta_log_rings_set_caps(big, 8192, 8192) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 1, "a") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 2, "b") == 0);
    memset(wide, 'Z', 47);
    wide[47] = '\0';
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 9, wide) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(strcmp(ent.text, wide) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 0, &ent) == 0);
    CHECK(ent.repeat == 2u);
    CHECK(strcmp(ent.text, TA_LOG_RINGS_OVERRUN_TEXT) == 0);
}

static void test_overrun_keeps_other_rings(void) {
    ta_log_rings_entry_t ent;
    uint32_t nb;
    char a[12];
    char b[12];
    char c[12];

    nb = ta_log_rings_node_bytes(11);
    CHECK(ta_log_rings_set_caps(8192, 8192, nb * 2u) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 1, "keep-me") == 0);
    fill11(a, 'I', '1');
    fill11(b, 'I', '2');
    fill11(c, 'I', '3');
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_INFO, 2, a) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_DEBUG, 3, b) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_VERBOSE, 4, c) == 0);

    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(strcmp(ent.text, "keep-me") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 2u);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 0, &ent) == 0);
    CHECK(strcmp(ent.text, b) == 0);
    CHECK(ent.level == TA_LOG_LEVEL_DEBUG);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 1, &ent) == 0);
    CHECK(strcmp(ent.text, c) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
}

static void test_warn_ring_overrun(void) {
    ta_log_rings_entry_t ent;
    uint32_t nb;
    char a[12];
    char b[12];
    char c[12];

    nb = ta_log_rings_node_bytes(11);
    CHECK(ta_log_rings_set_caps(8192, nb * 2u, 8192) == 0);
    fill11(a, 'W', '1');
    fill11(b, 'W', '2');
    fill11(c, 'W', '3');
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 1, a) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 2, b) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 3, c) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 2u);
    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 0, &ent) == 0);
    CHECK(strcmp(ent.text, TA_LOG_RINGS_OVERRUN_TEXT) == 0);
    CHECK(ent.repeat >= 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 1, &ent) == 0);
    CHECK(strcmp(ent.text, c) == 0);
    CHECK(ent.time_ms == 3u);
}

static void test_overrun_stress(void) {
    ta_log_rings_entry_t ent;
    uint32_t nb;
    int i;
    char msg[16];
    char oldest[16];

    nb = ta_log_rings_node_bytes(11);
    CHECK(ta_log_rings_set_caps(nb * 4u, 8192, 8192) == 0);
    for (i = 0; i < 30; i++) {
        snprintf(msg, sizeof(msg), "S-message%02d", i);
        CHECK(strlen(msg) == 11u);
        CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, (uint64_t)(100 + i), msg) ==
              0);
    }
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 4u);
    snprintf(oldest, sizeof(oldest), "S-message%02d", 26);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 0, &ent) == 0);
    CHECK(strcmp(ent.text, oldest) == 0);
    CHECK(ta_log_rings_at(TA_LOG_RING_ERROR, 3, &ent) == 0);
    CHECK(strcmp(ent.text, "S-message29") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 1u);
    CHECK(ta_log_rings_at(TA_LOG_RING_WARN, 0, &ent) == 0);
    CHECK(strcmp(ent.text, TA_LOG_RINGS_OVERRUN_TEXT) == 0);
    CHECK(ent.repeat == 26u);
}

static void test_merge_order(void) {
    ta_log_rings_entry_t ent;
    ta_log_rings_iter_t it;
    const char *expect_text[5];
    uint64_t expect_time[5];
    uint32_t expect_repeat[5];
    int n;

    CHECK(ta_log_rings_set_caps(4096, 4096, 4096) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_INFO, 10, "i") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 30, "w") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 20, "e") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_DEBUG, 20, "d") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_WARN, 30, "w") == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_VERBOSE, (1ull << 32) + 1ull, "v") ==
          0);

    expect_text[0] = "i";
    expect_time[0] = 10;
    expect_repeat[0] = 1;
    expect_text[1] = "e";
    expect_time[1] = 20;
    expect_repeat[1] = 1;
    expect_text[2] = "d";
    expect_time[2] = 20;
    expect_repeat[2] = 1;
    expect_text[3] = "w";
    expect_time[3] = 30;
    expect_repeat[3] = 2;
    expect_text[4] = "v";
    expect_time[4] = (1ull << 32) + 1ull;
    expect_repeat[4] = 1;

    memset(&it, 0, sizeof(it));
    CHECK(ta_log_rings_iter_begin(&it) == 0);
    n = 0;
    while (ta_log_rings_iter_next(&it, &ent)) {
        CHECK(n < 5);
        if (n < 5) {
            CHECK(strcmp(ent.text, expect_text[n]) == 0);
            CHECK(ent.time_ms == expect_time[n]);
            CHECK(ent.repeat == expect_repeat[n]);
        }
        if (n == 1) {
            CHECK(ent.ring == TA_LOG_RING_ERROR);
            CHECK(ent.level == TA_LOG_LEVEL_ERROR);
        }
        if (n == 2) {
            CHECK(ent.ring == TA_LOG_RING_INFO);
            CHECK(ent.level == TA_LOG_LEVEL_DEBUG);
            CHECK(ent.seq > 0u);
        }
        n++;
    }
    CHECK(n == 5);
    CHECK(ta_log_rings_iter_next(&it, &ent) == 0);
    ta_log_rings_iter_end(&it);
}

static void test_caps(void) {
    ta_log_rings_entry_t ent;

    CHECK(ta_log_rings_set_caps(100, 200, 300) == 0);
    CHECK(ta_log_rings_cap(TA_LOG_RING_ERROR) >= 100u);
    CHECK(ta_log_rings_cap(TA_LOG_RING_ERROR) % 8u == 0u);
    CHECK(ta_log_rings_cap(TA_LOG_RING_WARN) >= 200u);
    CHECK(ta_log_rings_cap(TA_LOG_RING_WARN) % 8u == 0u);
    CHECK(ta_log_rings_cap(TA_LOG_RING_INFO) >= 300u);
    CHECK(ta_log_rings_cap(TA_LOG_RING_INFO) % 8u == 0u);
    CHECK(ta_log_rings_cap(TA_LOG_RING_ERROR) == 104u);

    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_INFO, 1, "gone") == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 1u);
    CHECK(ta_log_rings_set_caps(4096, 4096, 4096) == 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_INFO) == 0u);
    CHECK(ta_log_rings_at(TA_LOG_RING_INFO, 0, &ent) != 0);

    CHECK(ta_log_rings_set_caps(0, 4096, 4096) == 0);
    CHECK(ta_log_rings_insert(TA_LOG_LEVEL_ERROR, 1, "no-room") != 0);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 0u);
    CHECK(ta_log_rings_count(TA_LOG_RING_WARN) == 0u);

    CHECK(ta_log_rings_reset() == 0);
    CHECK(ta_log_rings_cap(TA_LOG_RING_ERROR) == TA_LOG_RINGS_ERROR_CAP);
    CHECK(ta_log_rings_cap(TA_LOG_RING_WARN) == TA_LOG_RINGS_WARN_CAP);
    CHECK(ta_log_rings_cap(TA_LOG_RING_INFO) == TA_LOG_RINGS_INFO_CAP);
    CHECK(TA_LOG_RINGS_TOTAL_CAP == 512u * 1024u);
    CHECK(ta_log_rings_count(TA_LOG_RING_ERROR) == 0u);
    CHECK(ta_log_rings_node_bytes(TA_LOG_RINGS_TEXT_MAX + 1u) == 0u);
}

int main(void) {
    test_levels();
    test_repeat();
    test_overrun_drop_head();
    test_overrun_drops_until_fit();
    test_overrun_keeps_other_rings();
    test_warn_ring_overrun();
    test_overrun_stress();
    test_merge_order();
    test_caps();

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_log_rings: %d checks ok\n", checks);
    return 0;
}
