/* Host: SetRoute(MPD) then event reaches stub MPD; Sonos not hit; reply fields. */
#include "ta_event.h"
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

static ta_event_t g_mpd_last;
static int g_mpd_n;
static ta_event_t g_sonos_last;
static int g_sonos_n;

static int mpd_enqueue(const ta_event_t *ev) {
    g_mpd_last = *ev;
    g_mpd_n++;
    return 0;
}

static int sonos_enqueue(const ta_event_t *ev) {
    g_sonos_last = *ev;
    g_sonos_n++;
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
    const char msg[] = "toggle";

    ta_registry_reset();
    ta_router_reset();
    g_mpd_n = 0;
    g_sonos_n = 0;

    ta_router_start();
    CHECK(ta_registry_register("MPDController", mpd_enqueue) == 0);
    CHECK(ta_registry_register("SonosController", sonos_enqueue) == 0);

    CHECK(post_set_route("MPDController") == 0);
    CHECK(strcmp(ta_router_current_target(), "MPDController") == 0);

    ta_event_clear(&ev);
    ev.type = 100; /* control-ish */
    CHECK(ta_event_set_src(&ev, "Draw") == 0);
    ev.session_id = 77;
    CHECK(ta_event_set_reply(&ev, "Draw", 101) == 0);
    CHECK(ta_event_set_payload(&ev, msg, sizeof(msg)) == 0);
    CHECK(ta_registry_post(TA_CONTROLLER_NAME, &ev) == 0);

    CHECK(g_mpd_n == 1);
    CHECK(g_sonos_n == 0);
    CHECK(g_mpd_last.type == 100);
    CHECK(g_mpd_last.session_id == 77);
    CHECK(strcmp(g_mpd_last.reply_to, "Draw") == 0);
    CHECK(g_mpd_last.reply_type == 101);
    CHECK(g_mpd_last.payload_len == sizeof(msg));
    CHECK(memcmp(g_mpd_last.payload, msg, sizeof(msg)) == 0);
    CHECK(strcmp(g_mpd_last.src, "Draw") == 0);

    CHECK(post_set_route("SonosController") == 0);
    CHECK(ta_registry_post(TA_CONTROLLER_NAME, &ev) == 0);
    CHECK(g_sonos_n == 1);
    CHECK(g_mpd_n == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_router: %d checks ok\n", checks);
    return 0;
}
