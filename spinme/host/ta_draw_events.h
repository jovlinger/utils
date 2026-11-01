/* Draw TaskActor event interface (API + stub; no paint). */
#ifndef SPINME_TA_DRAW_EVENTS_H
#define SPINME_TA_DRAW_EVENTS_H

#include "ta_event.h"

#define TA_DRAW_NAME "Draw"

/* Draw-owned type range 0x200.. -- freeze for this interface item. */
enum {
    TA_EV_DRAW_UPDATE = 0x200,       /* rebuild dirty Shape pixels */
    TA_EV_DRAW_PAINT = 0x201,        /* push dirty UILayouts to glass */
    TA_EV_DRAW_REACT_TOUCH = 0x202,  /* from ISR mail / task */
    TA_EV_DRAW_REACT_ROTATE = 0x203,
    TA_EV_DRAW_SET_SHAPE_STACK = 0x204, /* Controller installs stack */
    TA_EV_DRAW_LOG = 0x205,          /* prefix then Logger */
    /* Completion replies (sent to reply_to when set). */
    TA_EV_DRAW_UPDATE_DONE = 0x210,
    TA_EV_DRAW_PAINT_DONE = 0x211
};

typedef struct ta_draw_stats {
    unsigned handled;
    unsigned unknown;
    unsigned replies_posted;
    unsigned update;
    unsigned paint;
    unsigned touch;
    unsigned rotate;
    unsigned set_stack;
    unsigned log;
} ta_draw_stats_t;

void ta_draw_reset(void);
void ta_draw_start(void);
int ta_draw_enqueue(const ta_event_t *ev);
/* Synchronous stub dispatch (also used by enqueue). */
int ta_draw_handle(const ta_event_t *ev);
const ta_draw_stats_t *ta_draw_stats(void);

#endif
