/* Draw TaskActor: sole glass owner (events, queue, ISR drain, dispatch). */
#ifndef SPINME_TA_DRAW_EVENTS_H
#define SPINME_TA_DRAW_EVENTS_H

#include "ta_event.h"
#include "ta_isr_mail.h"
#include "ta_queue.h"

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif


#define TA_DRAW_NAME "Draw"

/* Draw-owned type range 0x200.. */
enum {
    TA_EV_DRAW_UPDATE = 0x200,       /* cadence (no payload) or status (below) */
    TA_EV_DRAW_PAINT = 0x201,        /* phase1 + phase2 + push dirty exteriors */
    TA_EV_DRAW_REACT_TOUCH = 0x202,  /* x u16 LE, y u16 LE (same as ISR_TOUCH) */
    TA_EV_DRAW_REACT_ROTATE = 0x203, /* steps i8 (same as ISR_ROTARY) */
    TA_EV_DRAW_SET_SHAPE_STACK = 0x204, /* Controller installs follow chrome */
    TA_EV_DRAW_LOG = 0x205,          /* prefix then Logger */
    TA_EV_DRAW_SCROLL_OX = 0x206,    /* ox i16, or empty = step (cadence) */
    TA_EV_DRAW_SET_TEXT = 0x207,     /* [field u8][flags u8][ascii...] chunked */
    /* Completion replies (sent to reply_to when set). */
    TA_EV_DRAW_UPDATE_DONE = 0x210,
    TA_EV_DRAW_PAINT_DONE = 0x211,
    /* Inform bodies (Python SoT type ids; producers may adopt gradually). */
    TA_EV_DRAW_INFORM_SONGINFO = 0x220,
    TA_EV_DRAW_INFORM_VOLUME = 0x221,
    TA_EV_DRAW_INFORM_CURRPOS = 0x222
};

/* DRAW_UPDATE kinds live in ta_event.h (TA_DRAW_UPD_*). */

/* DRAW_SET_TEXT flags. A string arrives as FIRST .. LAST chunks. */
#define TA_DRAW_TEXT_FIRST 0x01u
#define TA_DRAW_TEXT_LAST 0x02u
#define TA_DRAW_TEXT_CHUNK TA_DRAW_TEXT_CHUNK_MAX

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
    unsigned scroll;
    unsigned set_text;
    unsigned isr_drained;
    unsigned isr_drops;
} ta_draw_stats_t;

void ta_draw_reset(void);
void ta_draw_start(void);
/* Registry enqueue: queue push when bound, else synchronous dispatch. */
int ta_draw_enqueue(const ta_event_envelope_t *env);
/* Dispatch one event on the Draw task (also used by enqueue when unbound). */
int ta_draw_handle(const ta_event_envelope_t *env);
const ta_draw_stats_t *ta_draw_stats(void);

/* Bind Draw's MP/SC queue (device: the Draw task consumes it). NULL unbinds. */
void ta_draw_bind_queue(ta_queue_t *q);
/*
 * Draw task turn: drain ISR mails into the queue (or handle them directly
 * when unbound), then peek -> handle -> pop until empty. Returns handled.
 */
size_t ta_draw_pump(ta_isr_mail_t *const *mails, size_t n_mails);

/* Producer helper: post ascii as SET_TEXT chunks to Draw. */
int ta_draw_post_text(uint8_t field, const char *ascii, ta_session_id_t session,
                      const char *src);
/* Producer helper: post DRAW_UPDATE status (0xFF = keep). */
int ta_draw_post_status(uint8_t polled, uint8_t desired, uint8_t playing,
                        uint8_t playing_polled, ta_session_id_t session,
                        const char *src);


#ifdef __cplusplus
}
#endif
#endif
