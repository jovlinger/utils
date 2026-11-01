/* Host: Router -> MPD/Sonos stubs; SetActive/ControlEvents; session_id. */
#include "ta_controller.h"
#include "ta_draw_events.h"
#include "ta_event.h"
#include "ta_net_events.h"
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

static ta_event_t g_cfg_last;
static int g_cfg_n;

static int config_sink(const ta_event_t *ev) {
    g_cfg_last = *ev;
    g_cfg_n++;
    return 0;
}

static int post_set_route(const char *target) {
    ta_event_t ev;

    ta_event_clear(&ev);
    ev.type = TA_EV_SET_ROUTE;
    CHECK(ta_event_set_src(&ev, "Config") == 0);
    ev.session_id = 1;
    CHECK(ta_event_set_payload(&ev, target, strlen(target)) == 0);
    return ta_registry_post(TA_CONTROLLER_NAME, &ev);
}

int main(void) {
    ta_event_t ev;

    ta_registry_reset();
    ta_router_reset();
    ta_mpd_reset();
    ta_sonos_reset();
    ta_draw_reset();
    ta_net_reset();
    g_cfg_n = 0;

    ta_router_start();
    ta_mpd_start();
    ta_sonos_start();
    ta_draw_start();
    ta_net_start();
    CHECK(ta_registry_register("Config", config_sink) == 0);

    CHECK(post_set_route(TA_MPD_NAME) == 0);

    ta_event_clear(&ev);
    ev.type = TA_EV_CTRL_SET_ACTIVE;
    ev.session_id = 88;
    CHECK(ta_event_set_src(&ev, "Config") == 0);
    CHECK(ta_registry_post(TA_CONTROLLER_NAME, &ev) == 0);
    CHECK(ta_mpd_stats()->set_active == 1);
    CHECK(ta_sonos_stats()->set_active == 0);
    CHECK(ta_draw_stats()->set_stack == 1);
    CHECK(ta_net_stats()->set_dialect == 1);

    ta_event_clear(&ev);
    ev.type = TA_EV_CTRL_TOGGLE;
    ev.session_id = 88;
    CHECK(ta_event_set_src(&ev, "Draw") == 0);
    CHECK(ta_event_set_reply(&ev, "Config", TA_EV_CTRL_TOGGLE) == 0);
    CHECK(ta_registry_post(TA_CONTROLLER_NAME, &ev) == 0);
    CHECK(ta_mpd_stats()->toggle == 1);
    CHECK(ta_mpd_stats()->replies_posted == 1);
    CHECK(g_cfg_n == 1);
    CHECK(g_cfg_last.session_id == 88);
    CHECK(strcmp(g_cfg_last.src, TA_MPD_NAME) == 0);

    CHECK(post_set_route(TA_SONOS_NAME) == 0);
    ta_event_clear(&ev);
    ev.type = TA_EV_CTRL_VOLUME;
    ev.session_id = 9;
    CHECK(ta_event_set_src(&ev, "Draw") == 0);
    CHECK(ta_registry_post(TA_CONTROLLER_NAME, &ev) == 0);
    CHECK(ta_sonos_stats()->volume == 1);
    CHECK(ta_mpd_stats()->volume == 0);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_controller: %d checks ok\n", checks);
    return 0;
}
