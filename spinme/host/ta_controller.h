/* MPDController + SonosController stubs (ControlEvents surface). */
#ifndef SPINME_TA_CONTROLLER_H
#define SPINME_TA_CONTROLLER_H

#include "ta_event.h"
#include "ta_net_events.h" /* ControlEvents + Net types */

#define TA_MPD_NAME "MPDController"
#define TA_SONOS_NAME "SonosController"

typedef struct ta_controller_stats {
    unsigned handled;
    unsigned unknown;
    unsigned set_active;
    unsigned toggle;
    unsigned volume;
    unsigned next;
    unsigned prev;
    unsigned replies_posted;
} ta_controller_stats_t;

void ta_mpd_reset(void);
void ta_mpd_start(void);
int ta_mpd_enqueue(const ta_event_t *ev);
const ta_controller_stats_t *ta_mpd_stats(void);

void ta_sonos_reset(void);
void ta_sonos_start(void);
int ta_sonos_enqueue(const ta_event_t *ev);
const ta_controller_stats_t *ta_sonos_stats(void);

#endif
