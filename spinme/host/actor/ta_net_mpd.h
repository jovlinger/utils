/* Net MPD dialect: non-blocking poll/set, coalesce volume, albumart reply. */
#ifndef SPINME_TA_NET_MPD_H
#define SPINME_TA_NET_MPD_H

#include "ta_net_events.h"

typedef enum {
    TA_MPD_IDLE = 0,
    TA_MPD_POLL_PENDING = 1,
    TA_MPD_ALBUMART_PENDING = 2
} ta_mpd_phase_t;

typedef struct ta_net_mpd {
    ta_mpd_phase_t phase;
    int volume;          /* last coalesced desired volume */
    int volume_dirty;    /* set pending, not yet "sent" */
    unsigned polls;
    unsigned sets;
    unsigned noops;
    unsigned albumarts;
    char reply_to[TA_NAME_MAX];
    ta_session_id_t session_id;
} ta_net_mpd_t;

void ta_net_mpd_reset(ta_net_mpd_t *m);
/* Handle Net events for MPD dialect. */
int ta_net_mpd_handle(ta_net_mpd_t *m, const ta_event_envelope_t *env);
/* Fake host tick: complete pending poll/albumart with reply_to. */
int ta_net_mpd_tick(ta_net_mpd_t *m);

#endif
