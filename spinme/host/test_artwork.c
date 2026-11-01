/* Host: calm filter, default-art suppress, album-change oneshots. */
#include "ta_artwork.h"
#include "ta_draw_events.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_sched_events.h"

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

static int g_poll;
static int g_upd;

static int net_sink(const ta_event_t *ev) {
    if (ev->type == TA_EV_NET_POLL) {
        g_poll++;
    }
    return 0;
}

static int draw_sink(const ta_event_t *ev) {
    if (ev->type == TA_EV_DRAW_UPDATE) {
        g_upd++;
    }
    return 0;
}

int main(void) {
    uint8_t rgba[4 * 4 * 4];
    size_t i;

    for (i = 0; i < 16; i++) {
        rgba[i * 4] = 255;
        rgba[i * 4 + 1] = 0;
        rgba[i * 4 + 2] = 0;
        rgba[i * 4 + 3] = 255;
    }
    ta_artwork_calm_rgba(rgba, 4, 4);
    CHECK(rgba[0] < 255); /* blurred/desat */

    CHECK(ta_artwork_is_default(TA_ART_DEFAULT_FP) == 1);
    CHECK(ta_artwork_is_default(0x1234) == 0);

    ta_registry_reset();
    ta_sched_reset();
    g_poll = g_upd = 0;
    ta_sched_start();
    CHECK(ta_registry_register(TA_NET_NAME, net_sink) == 0);
    CHECK(ta_registry_register(TA_DRAW_NAME, draw_sink) == 0);
    CHECK(ta_artwork_on_album_change(TA_NET_NAME, TA_DRAW_NAME, 3, 200) == 0);
    ta_sched_advance_ms(50);
    CHECK(g_poll == 1);
    ta_sched_advance_ms(150);
    CHECK(g_upd == 1);

    if (failures != 0) {
        fprintf(stderr, "%d/%d checks failed\n", failures, checks);
        return 1;
    }
    printf("test_artwork: %d checks ok\n", checks);
    return 0;
}
