/* Host: follow chrome UILayouts; paint-once static; high-z clock/title. */
#include "ta_follow_chrome.h"

#include <stdio.h>

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
    ta_follow_chrome_t chrome;
    unsigned shapes[TA_FOLLOW_N] = {1, 2, 3, 4, 5, 6, 7, 8};
    size_t i;

    CHECK(ta_follow_chrome_build(&chrome, shapes) == 0);
    CHECK(chrome.n == TA_FOLLOW_N);

    /* Farthest = base; nearest = clock. */
    CHECK(ta_uilo_shape(chrome.uilo[TA_FOLLOW_BASE]) == 1);
    CHECK(ta_uilo_shape(chrome.uilo[TA_FOLLOW_CLOCK]) == 8);
    CHECK(ta_uilo_y(chrome.uilo[TA_FOLLOW_CLOCK]) <
          ta_uilo_y(chrome.uilo[TA_FOLLOW_TITLE]));

    for (i = 0; i < chrome.n; i++) {
        if (ta_follow_is_high_z_dynamic((unsigned)i)) {
            CHECK(chrome.paint_once[i] == 0);
        } else {
            CHECK(chrome.paint_once[i] == 1);
        }
    }
    CHECK(chrome.accept_hit[TA_FOLLOW_TRANSPORT] == 1);
    CHECK(chrome.accept_hit[TA_FOLLOW_BASE] == 0);
    CHECK(ta_follow_is_high_z_dynamic(TA_FOLLOW_CLOCK) == 1);
    CHECK(ta_follow_is_high_z_dynamic(TA_FOLLOW_TITLE) == 1);
    CHECK(ta_follow_is_high_z_dynamic(TA_FOLLOW_ZONE) == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_follow_chrome: %d checks ok\n", checks);
    return 0;
}
