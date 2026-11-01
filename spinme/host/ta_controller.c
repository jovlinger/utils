#include "ta_controller.h"

#include "ta_draw_events.h"
#include "ta_registry.h"

#include <string.h>

static ta_controller_stats_t g_mpd;
static ta_controller_stats_t g_sonos;

void ta_mpd_reset(void) {
    memset(&g_mpd, 0, sizeof(g_mpd));
}

void ta_sonos_reset(void) {
    memset(&g_sonos, 0, sizeof(g_sonos));
}

const ta_controller_stats_t *ta_mpd_stats(void) {
    return &g_mpd;
}

const ta_controller_stats_t *ta_sonos_stats(void) {
    return &g_sonos;
}

static void maybe_reply(ta_controller_stats_t *st, const ta_event_t *ev,
                        ta_event_type_t done_type, const char *src) {
    ta_event_t reply;

    if (ev->reply_to[0] == '\0') {
        return;
    }
    ta_event_clear(&reply);
    reply.type = done_type;
    reply.session_id = ev->session_id;
    (void)ta_event_set_src(&reply, src);
    if (ta_registry_post(ev->reply_to, &reply) == 0) {
        st->replies_posted++;
    }
}

static int handle(ta_controller_stats_t *st, const ta_event_t *ev,
                  const char *src) {
    ta_event_t out;

    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_CTRL_SET_ACTIVE:
        st->set_active++;
        st->handled++;
        /* Stub: ask Draw for stack; ask Net for dialect. */
        ta_event_clear(&out);
        out.type = TA_EV_DRAW_SET_SHAPE_STACK;
        out.session_id = ev->session_id;
        (void)ta_event_set_src(&out, src);
        (void)ta_registry_post(TA_DRAW_NAME, &out);
        ta_event_clear(&out);
        out.type = TA_EV_NET_SET_DIALECT;
        out.session_id = ev->session_id;
        (void)ta_event_set_src(&out, src);
        (void)ta_registry_post(TA_NET_NAME, &out);
        maybe_reply(st, ev, TA_EV_CTRL_SET_ACTIVE, src);
        return 0;
    case TA_EV_CTRL_TOGGLE:
        st->toggle++;
        st->handled++;
        maybe_reply(st, ev, TA_EV_CTRL_TOGGLE, src);
        return 0;
    case TA_EV_CTRL_VOLUME:
        st->volume++;
        st->handled++;
        maybe_reply(st, ev, TA_EV_CTRL_VOLUME, src);
        return 0;
    case TA_EV_CTRL_NEXT:
        st->next++;
        st->handled++;
        return 0;
    case TA_EV_CTRL_PREV:
        st->prev++;
        st->handled++;
        return 0;
    default:
        st->unknown++;
        return -1;
    }
}

int ta_mpd_enqueue(const ta_event_t *ev) {
    return handle(&g_mpd, ev, TA_MPD_NAME);
}

int ta_sonos_enqueue(const ta_event_t *ev) {
    return handle(&g_sonos, ev, TA_SONOS_NAME);
}

void ta_mpd_start(void) {
    (void)ta_registry_register(TA_MPD_NAME, ta_mpd_enqueue);
}

void ta_sonos_start(void) {
    (void)ta_registry_register(TA_SONOS_NAME, ta_sonos_enqueue);
}
