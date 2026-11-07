/* Host: follow chrome UILayouts; paint-once static; high-z clock/title. */
#include "ta_chrome_icons.h"
#include "ta_follow_chrome.h"

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
    ta_follow_chrome_t chrome;
    unsigned shapes[TA_FOLLOW_N] = {1, 2, 3, 4, 5, 6, 7, 8, 9};
    ta_follow_metrics_t m;
    size_t i;

    CHECK(ta_follow_chrome_build(&chrome, shapes) == 0);
    CHECK(chrome.n == TA_FOLLOW_N);

    CHECK(ta_uilo_shape(chrome.uilo[TA_FOLLOW_BASE]) == 1);
    CHECK(ta_uilo_shape(chrome.uilo[TA_FOLLOW_CLOCK]) == 8);
    CHECK(ta_uilo_shape(chrome.uilo[TA_FOLLOW_NAV]) == 9);

    memset(&m, 0, sizeof(m));
    m.panel_w = 360;
    m.panel_h = 360;
    m.text_x = 20;
    m.text_y = 40;
    m.text_h = 10;
    m.gap = 4;
    m.button_y = 12;
    m.transport_w = TA_CHROME_ICON_PX;
    m.transport_h = TA_CHROME_ICON_PX;
    m.nav_w = TA_CHROME_NAV_PX;
    m.nav_h = TA_CHROME_NAV_PX;
    CHECK(ta_follow_chrome_place(&chrome, &m) == 0);
    CHECK(ta_uilo_y(chrome.uilo[TA_FOLLOW_NAV]) == 12);
    CHECK(ta_uilo_x(chrome.uilo[TA_FOLLOW_TRANSPORT]) ==
          (360 - TA_CHROME_ICON_PX) / 2);
    CHECK(ta_uilo_y(chrome.uilo[TA_FOLLOW_TRANSPORT]) ==
          (360 - TA_CHROME_ICON_PX) / 2);

    for (i = 0; i < chrome.n; i++) {
        if (ta_follow_is_high_z_dynamic((unsigned)i)) {
            CHECK(chrome.paint_once[i] == 0);
        } else {
            CHECK(chrome.paint_once[i] == 1);
        }
    }
    CHECK(chrome.accept_hit[TA_FOLLOW_TRANSPORT] == 1);
    CHECK(chrome.accept_hit[TA_FOLLOW_NAV] == 1);
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
