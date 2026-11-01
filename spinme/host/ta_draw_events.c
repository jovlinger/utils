#include "ta_draw_events.h"

#include "ta_registry.h"

#include <string.h>

static ta_draw_stats_t g_stats;

void ta_draw_reset(void) {
    memset(&g_stats, 0, sizeof(g_stats));
}

const ta_draw_stats_t *ta_draw_stats(void) {
    return &g_stats;
}

static void maybe_reply(const ta_event_t *ev, ta_event_type_t done_type) {
    ta_event_t reply;

    if (ev->reply_to[0] == '\0') {
        return;
    }
    ta_event_clear(&reply);
    reply.type = done_type;
    reply.session_id = ev->session_id;
    (void)ta_event_set_src(&reply, TA_DRAW_NAME);
    if (ta_registry_post(ev->reply_to, &reply) == 0) {
        g_stats.replies_posted++;
    }
}

int ta_draw_handle(const ta_event_t *ev) {
    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_DRAW_UPDATE:
        g_stats.update++;
        g_stats.handled++;
        maybe_reply(ev, TA_EV_DRAW_UPDATE_DONE);
        return 0;
    case TA_EV_DRAW_PAINT:
        g_stats.paint++;
        g_stats.handled++;
        maybe_reply(ev, TA_EV_DRAW_PAINT_DONE);
        return 0;
    case TA_EV_DRAW_REACT_TOUCH:
        g_stats.touch++;
        g_stats.handled++;
        return 0;
    case TA_EV_DRAW_REACT_ROTATE:
        g_stats.rotate++;
        g_stats.handled++;
        return 0;
    case TA_EV_DRAW_SET_SHAPE_STACK:
        g_stats.set_stack++;
        g_stats.handled++;
        return 0;
    case TA_EV_DRAW_LOG:
        g_stats.log++;
        g_stats.handled++;
        return 0;
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_draw_enqueue(const ta_event_t *ev) {
    return ta_draw_handle(ev);
}

void ta_draw_start(void) {
    (void)ta_registry_register(TA_DRAW_NAME, ta_draw_enqueue);
}
