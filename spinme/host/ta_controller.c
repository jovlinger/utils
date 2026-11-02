#include "ta_controller.h"

#include "ta_draw_events.h"
#include "ta_net_backend.h"
#include "ta_registry.h"
#include "ta_sched_events.h"

#include <string.h>

/* Who asked for a transport/volume change; echoed on SET_DONE. */
typedef struct {
    char reply_to[TA_NAME_MAX];
    ta_event_type_t reply_type;
    ta_session_id_t session_id;
} ta_origin_t;

typedef struct {
    ta_controller_stats_t st;
    int volume;            /* model 0..100 */
    int set_inflight;      /* NET_SET awaiting SET_DONE */
    int poll_inflight;     /* NET_POLL awaiting POLL_DONE */
    int toggle_pending;    /* coalesced behind in-flight SET */
    int vol_dirty;         /* model changed while SET in flight */
    ta_session_id_t session; /* last ControlEvent session (for Net posts) */
    ta_origin_t inflight_origin;
    ta_origin_t queued_origin;
} ta_mpd_state_t;

static ta_mpd_state_t g_mpd;
static ta_controller_stats_t g_sonos;

void ta_mpd_reset(void) {
    memset(&g_mpd, 0, sizeof(g_mpd));
    g_mpd.volume = TA_MPD_VOL_DEFAULT;
}

void ta_sonos_reset(void) {
    memset(&g_sonos, 0, sizeof(g_sonos));
}

const ta_controller_stats_t *ta_mpd_stats(void) {
    return &g_mpd.st;
}

const ta_controller_stats_t *ta_sonos_stats(void) {
    return &g_sonos;
}

int ta_mpd_volume(void) {
    return g_mpd.volume;
}

int ta_mpd_set_inflight(void) {
    return g_mpd.set_inflight;
}

int ta_mpd_poll_inflight(void) {
    return g_mpd.poll_inflight;
}

static void origin_from(ta_origin_t *o, const ta_event_t *ev) {
    memcpy(o->reply_to, ev->reply_to, TA_NAME_MAX);
    o->reply_type = ev->reply_type;
    o->session_id = ev->session_id;
}

static void origin_reply(ta_controller_stats_t *st, const ta_origin_t *o,
                         ta_event_type_t fallback_type, const char *src) {
    ta_event_t reply;

    if (o->reply_to[0] == '\0') {
        return;
    }
    ta_event_clear(&reply);
    reply.type = o->reply_type != 0 ? o->reply_type : fallback_type;
    reply.session_id = o->session_id;
    (void)ta_event_set_src(&reply, src);
    if (ta_registry_post(o->reply_to, &reply) == 0) {
        st->replies_posted++;
    }
}

static void maybe_reply(ta_controller_stats_t *st, const ta_event_t *ev,
                        ta_event_type_t done_type, const char *src) {
    ta_origin_t o;

    origin_from(&o, ev);
    origin_reply(st, &o, done_type, src);
}

/* ---- MPDController ---------------------------------------------------- */

static int clamp_vol(int v) {
    if (v < 0) {
        return 0;
    }
    if (v > 100) {
        return 100;
    }
    return v;
}

/* Post NET_SET with reply_to=MPDController; mark in flight. Note that Net
 * may complete synchronously (host stub), so in-flight is set BEFORE post
 * and the DONE handler clears it. */
static int mpd_post_set(const uint8_t *pl, size_t len,
                        const ta_origin_t *origin) {
    ta_event_t out;

    ta_event_clear(&out);
    out.type = TA_EV_NET_SET;
    out.session_id = g_mpd.session;
    (void)ta_event_set_src(&out, TA_MPD_NAME);
    (void)ta_event_set_reply(&out, TA_MPD_NAME, TA_EV_NET_SET_DONE);
    (void)ta_event_set_payload(&out, pl, len);
    g_mpd.set_inflight = 1;
    g_mpd.inflight_origin = *origin;
    if (ta_registry_post(TA_NET_NAME, &out) != 0) {
        g_mpd.set_inflight = 0;
        memset(&g_mpd.inflight_origin, 0, sizeof(g_mpd.inflight_origin));
        return -1;
    }
    g_mpd.st.net_set_posted++;
    return 0;
}

static int mpd_post_toggle(const ta_origin_t *origin) {
    uint8_t pl[1];

    pl[0] = (uint8_t)TA_NET_SET_OP_TOGGLE;
    return mpd_post_set(pl, 1, origin);
}

static int mpd_post_volume(const ta_origin_t *origin) {
    uint8_t pl[2];

    pl[0] = (uint8_t)TA_NET_SET_OP_VOLUME;
    pl[1] = (uint8_t)g_mpd.volume;
    return mpd_post_set(pl, 2, origin);
}

static int mpd_post_poll(void) {
    ta_event_t out;

    ta_event_clear(&out);
    out.type = TA_EV_NET_POLL;
    out.session_id = g_mpd.session;
    (void)ta_event_set_src(&out, TA_MPD_NAME);
    (void)ta_event_set_reply(&out, TA_MPD_NAME, TA_EV_NET_POLL_DONE);
    g_mpd.poll_inflight = 1;
    if (ta_registry_post(TA_NET_NAME, &out) != 0) {
        g_mpd.poll_inflight = 0;
        return -1;
    }
    g_mpd.st.net_poll_posted++;
    return 0;
}

static void mpd_flush_or_poll(void) {
    ta_origin_t o = g_mpd.queued_origin;

    memset(&g_mpd.queued_origin, 0, sizeof(g_mpd.queued_origin));
    if (g_mpd.toggle_pending) {
        g_mpd.toggle_pending = 0;
        (void)mpd_post_toggle(&o);
        return;
    }
    if (g_mpd.vol_dirty) {
        g_mpd.vol_dirty = 0;
        (void)mpd_post_volume(&o);
        return;
    }
    /* Settled: refresh status so chrome follows the player. */
    if (!g_mpd.poll_inflight) {
        (void)mpd_post_poll();
    }
}

static int mpd_handle(const ta_event_t *ev) {
    ta_controller_stats_t *st = &g_mpd.st;
    ta_event_t out;
    ta_origin_t origin;

    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_CTRL_SET_ACTIVE:
        st->set_active++;
        st->handled++;
        g_mpd.session = ev->session_id;
        ta_event_clear(&out);
        out.type = TA_EV_DRAW_SET_SHAPE_STACK;
        out.session_id = ev->session_id;
        (void)ta_event_set_src(&out, TA_MPD_NAME);
        (void)ta_registry_post(TA_DRAW_NAME, &out);
        ta_event_clear(&out);
        out.type = TA_EV_NET_SET_DIALECT;
        out.session_id = ev->session_id;
        (void)ta_event_set_src(&out, TA_MPD_NAME);
        (void)ta_registry_post(TA_NET_NAME, &out);
        /* Poll cadence: Scheduler -> CTRL_POLL -> NET_POLL. Missing
         * Scheduler (unit tests) is not an error here. */
        (void)ta_sched_arm_periodic(TA_MPD_NAME, ev->session_id,
                                    TA_MPD_POLL_MS, TA_EV_CTRL_POLL);
        maybe_reply(st, ev, TA_EV_CTRL_SET_ACTIVE, TA_MPD_NAME);
        return 0;
    case TA_EV_CTRL_TOGGLE:
        st->toggle++;
        st->handled++;
        g_mpd.session = ev->session_id;
        origin_from(&origin, ev);
        if (origin.reply_type == 0) {
            origin.reply_type = TA_EV_CTRL_TOGGLE;
        }
        if (g_mpd.set_inflight) {
            st->coalesced++;
            g_mpd.toggle_pending = 1;
            g_mpd.queued_origin = origin;
            return 0;
        }
        return mpd_post_toggle(&origin);
    case TA_EV_CTRL_VOLUME: {
        int before = g_mpd.volume;

        st->volume++;
        st->handled++;
        g_mpd.session = ev->session_id;
        if (ev->payload_len == 1) {
            g_mpd.volume = clamp_vol(before + (int)(int8_t)ev->payload[0]);
        } else if (ev->payload_len >= 2 &&
                   ev->payload[0] == TA_CTRL_VOL_ABS) {
            g_mpd.volume = clamp_vol((int)ev->payload[1]);
        }
        origin_from(&origin, ev);
        if (origin.reply_type == 0) {
            origin.reply_type = TA_EV_CTRL_VOLUME;
        }
        if (g_mpd.volume == before) {
            /* Touch on chrome or no-op step: nothing for Net. */
            origin_reply(st, &origin, TA_EV_CTRL_VOLUME, TA_MPD_NAME);
            return 0;
        }
        if (g_mpd.set_inflight) {
            st->coalesced++;
            g_mpd.vol_dirty = 1;
            g_mpd.queued_origin = origin;
            return 0;
        }
        return mpd_post_volume(&origin);
    }
    case TA_EV_CTRL_POLL:
        st->handled++;
        if (g_mpd.poll_inflight) {
            st->polls_skipped++;
            return 0;
        }
        return mpd_post_poll();
    case TA_EV_NET_SET_DONE: {
        ta_origin_t o = g_mpd.inflight_origin;

        st->set_done++;
        st->handled++;
        g_mpd.set_inflight = 0;
        memset(&g_mpd.inflight_origin, 0, sizeof(g_mpd.inflight_origin));
        origin_reply(st, &o, TA_EV_NET_SET_DONE, TA_MPD_NAME);
        mpd_flush_or_poll();
        return 0;
    }
    case TA_EV_NET_POLL_DONE:
        st->poll_done++;
        st->handled++;
        g_mpd.poll_inflight = 0;
        /* Draw WI: DRAW_UPDATE with status fields goes here. */
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

/* ---- SonosController (stub: counts + echo) ----------------------------- */

static int sonos_handle(const ta_event_t *ev) {
    ta_controller_stats_t *st = &g_sonos;

    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_CTRL_SET_ACTIVE:
        st->set_active++;
        st->handled++;
        maybe_reply(st, ev, TA_EV_CTRL_SET_ACTIVE, TA_SONOS_NAME);
        return 0;
    case TA_EV_CTRL_TOGGLE:
        st->toggle++;
        st->handled++;
        maybe_reply(st, ev, TA_EV_CTRL_TOGGLE, TA_SONOS_NAME);
        return 0;
    case TA_EV_CTRL_VOLUME:
        st->volume++;
        st->handled++;
        maybe_reply(st, ev, TA_EV_CTRL_VOLUME, TA_SONOS_NAME);
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
    return mpd_handle(ev);
}

int ta_sonos_enqueue(const ta_event_t *ev) {
    return sonos_handle(ev);
}

void ta_mpd_start(void) {
    (void)ta_registry_register(TA_MPD_NAME, ta_mpd_enqueue);
}

void ta_sonos_start(void) {
    (void)ta_registry_register(TA_SONOS_NAME, ta_sonos_enqueue);
}
