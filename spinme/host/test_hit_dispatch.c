/* Host: accept_hit walk -> ControlEvents via Router. */
#include "ta_controller.h"
#include "ta_follow_chrome.h"
#include "ta_hit_dispatch.h"
#include "ta_registry.h"
#include "ta_router.h"

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
    unsigned shapes[TA_FOLLOW_N] = {1, 2, 3, 4, 5, 6, 7, 8};
    uint16_t sw[TA_FOLLOW_N];
    uint16_t sh[TA_FOLLOW_N];
    size_t i;
    ta_event_envelope_t route;

    for (i = 0; i < TA_FOLLOW_N; i++) {
        sw[i] = 40;
        sh[i] = 20;
    }

    ta_registry_reset();
    ta_router_reset();
    ta_mpd_reset();
    ta_net_reset();
    ta_router_start();
    ta_mpd_start();
    ta_net_start(); /* MPD now posts NET_SET; stub Net replies at once */

    ta_env_clear(&route);
    route.event.type = TA_EV_SET_ROUTE;
    (void)ta_env_set_src(&route, "Config");
    (void)ta_event_set_ctrl_set_route(&route.event, TA_MPD_NAME);
    CHECK(ta_registry_post(TA_CONTROLLER_NAME, &route) == 0);

    CHECK(ta_follow_chrome_build(&chrome, shapes) == 0);

    /* Miss. */
    CHECK(ta_react_touch(&chrome, 0, 0, 9, sw, sh) == 1);
    CHECK(ta_mpd_stats()->toggle == 0);

    /* Transport hit. */
    {
        int tx = ta_uilo_x(chrome.uilo[TA_FOLLOW_TRANSPORT]) + 1;
        int ty = ta_uilo_y(chrome.uilo[TA_FOLLOW_TRANSPORT]) + 1;
        CHECK(ta_react_touch(&chrome, (uint16_t)tx, (uint16_t)ty, 9, sw, sh) ==
              0);
        CHECK(ta_mpd_stats()->toggle == 1);
    }

    CHECK(ta_react_rotate(3, 9) == 0);
    CHECK(ta_mpd_stats()->volume == 1);
    CHECK(ta_mpd_volume() == TA_MPD_VOL_DEFAULT + 3);
    CHECK(ta_net_stats()->set == 2); /* toggle + volume reached Net */

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_hit_dispatch: %d checks ok\n", checks);
    return 0;
}
