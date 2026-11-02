/* MPDController (real: drives Net) + SonosController stub (ControlEvents). */
#ifndef SPINME_TA_CONTROLLER_H
#define SPINME_TA_CONTROLLER_H

#include "ta_event.h"
#include "ta_net_events.h" /* ControlEvents + Net types */

#ifdef __cplusplus
extern "C" {
#endif


#define TA_MPD_NAME "MPDController"
#define TA_SONOS_NAME "SonosController"

/* Poll cadence armed on CTRL_SET_ACTIVE: Scheduler -> CTRL_POLL -> NET_POLL. */
#ifndef TA_MPD_POLL_MS
#define TA_MPD_POLL_MS 2000u
#endif
/* Volume model before any poll/absolute set has seeded it. */
#ifndef TA_MPD_VOL_DEFAULT
#define TA_MPD_VOL_DEFAULT 50
#endif

/*
 * CTRL_VOLUME payload:
 *   len 0 : touch on volume chrome; no Net traffic (model unchanged).
 *   len 1 : i8 relative steps (rotary); model += steps, clamped 0..100.
 *   len 2 : [TA_CTRL_VOL_ABS, level] absolute 0..100.
 * Any change posts NET_SET [VOLUME, level]; while a SET is in flight the
 * latest level is coalesced and sent on SET_DONE.
 */
#define TA_CTRL_VOL_ABS 0x01u

typedef struct ta_controller_stats {
    unsigned handled;
    unsigned unknown;
    unsigned set_active;
    unsigned toggle;
    unsigned volume;
    unsigned next;
    unsigned prev;
    unsigned replies_posted;
    /* MPD -> Net traffic. */
    unsigned net_set_posted;
    unsigned net_poll_posted;
    unsigned polls_skipped; /* CTRL_POLL while a poll was in flight */
    unsigned coalesced;     /* volume/toggle deferred behind in-flight SET */
    unsigned set_done;
    unsigned poll_done;
    unsigned draw_status_posted; /* DRAW_UPDATE status toward Draw */
} ta_controller_stats_t;

void ta_mpd_reset(void);
void ta_mpd_start(void);
int ta_mpd_enqueue(const ta_event_t *ev);
const ta_controller_stats_t *ta_mpd_stats(void);
/* Current volume model (0..100). */
int ta_mpd_volume(void);
/* Last player-reported volume / playing from POLL_DONE; -1 unknown. */
int ta_mpd_polled(void);
int ta_mpd_playing(void);
/* Nonzero while a NET_SET / NET_POLL awaits its DONE. */
int ta_mpd_set_inflight(void);
int ta_mpd_poll_inflight(void);

void ta_sonos_reset(void);
void ta_sonos_start(void);
int ta_sonos_enqueue(const ta_event_t *ev);
const ta_controller_stats_t *ta_sonos_stats(void);


#ifdef __cplusplus
}
#endif
#endif
