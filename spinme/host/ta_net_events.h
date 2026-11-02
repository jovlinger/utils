/* Net TaskActor event interface (API + stub; no HTTP). */
#ifndef SPINME_TA_NET_EVENTS_H
#define SPINME_TA_NET_EVENTS_H

#include "ta_event.h"

#ifdef __cplusplus
extern "C" {
#endif


#define TA_NET_NAME "Net"

/* Net-owned type range 0x300.. */
enum {
    TA_EV_NET_SET_DIALECT = 0x300, /* MPD vs Sonos wire dialect */
    TA_EV_NET_POLL = 0x301,        /* status poll request */
    TA_EV_NET_SET = 0x302,         /* volume/transport set */
    TA_EV_NET_ALBUMART = 0x303,    /* fetch artwork */
    /* Completions (post to reply_to). */
    TA_EV_NET_POLL_DONE = 0x310,
    TA_EV_NET_SET_DONE = 0x311,
    TA_EV_NET_ALBUMART_DONE = 0x312
};

/* ControlEvents (toward Controller via Router) -- shared surface doc. */
enum {
    TA_EV_CTRL_TOGGLE = 0x400,
    TA_EV_CTRL_VOLUME = 0x401,
    TA_EV_CTRL_NEXT = 0x402,
    TA_EV_CTRL_PREV = 0x403,
    TA_EV_CTRL_SET_ACTIVE = 0x404
};

typedef struct ta_net_stats {
    unsigned handled;
    unsigned unknown;
    unsigned set_dialect;
    unsigned poll;
    unsigned set;
    unsigned albumart;
    unsigned replies_posted;
} ta_net_stats_t;

void ta_net_reset(void);
void ta_net_start(void);
int ta_net_enqueue(const ta_event_t *ev);
int ta_net_handle(const ta_event_t *ev);
const ta_net_stats_t *ta_net_stats(void);


#ifdef __cplusplus
}
#endif
#endif
