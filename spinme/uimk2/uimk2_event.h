/* uimk2 Core B event ring. See spinme/DESIGN.md "Event queue" and
 * spinme/docs/JOHANDESIGN.md "Core B events".
 *
 * An event is a tagged union stored by value in a ring of QUEUE_DEPTH slots.
 * The selector is a small int enum; the handler is one switch on it. There
 * are no function pointers on events.
 *
 * push writes the struct at the tail and then advances the tail. peek returns
 * a pointer into the ring, or NULL when empty. The handler runs on that
 * pointer, and only then does pop advance the head, so the slot stays owned
 * for the whole handler. A push into a full ring logs ERROR, counts the drop,
 * and returns false. Nothing is replaced in place: a later volume does not
 * overwrite an earlier one still in the ring.
 *
 * Core A posts only press, pooled volume, screen_on, and screen_off. Core B
 * pushes toggle, redraw, update_render_draw, clock, and player_poll from its
 * handler and schedulers. Invalidate is not an event.
 *
 * The ring itself is not locked; events are the unit of locking between the
 * cores. The firmware wraps push in whatever its inter-core post needs.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_EVENT_H
#define UIMK2_EVENT_H

#include <stdbool.h>
#include <stdint.h>

#include "uimk2_config.h"

/* Function selector. 0 is reserved so a zeroed slot is visibly empty. */
typedef enum {
    UIMK2_EV_NONE = 0,
    UIMK2_EV_PRESS,              /* A: hit-test (x, y) down the zlist */
    UIMK2_EV_VOLUME,             /* A: pooled clicks; B owns desired */
    UIMK2_EV_TOGGLE,             /* B: local play/pause, command the player */
    UIMK2_EV_SCREEN_ON,          /* A: backlight on, arm poll and screen-off */
    UIMK2_EV_SCREEN_OFF,         /* A: backlight off, stop the poll scheduler */
    UIMK2_EV_UPDATE_RENDER_DRAW, /* B: update, render into next, ping A */
    UIMK2_EV_REDRAW,             /* B: retry compare/swap/ping if A was busy */
    UIMK2_EV_CLOCK,              /* B: store logical second and absolute tick */
    UIMK2_EV_PLAYER_POLL,        /* B: refresh player variables over the net */
    UIMK2_EV_COUNT
} uimk2_event_sel;

typedef struct {
    uint8_t selector; /* uimk2_event_sel */
    union {
        struct {
            int x, y;
        } press;
        struct {
            int new_val;
        } volume;
        struct {
            int attempt;
        } redraw;
        /* toggle, screen_on, screen_off, update_render_draw, clock,
         * player_poll: selector only */
    } u;
} uimk2_event;

typedef struct {
    uimk2_event slot[QUEUE_DEPTH];
    uint32_t head;    /* next slot to peek / pop */
    uint32_t tail;    /* next slot to write */
    uint32_t len;     /* occupied slots, 0..QUEUE_DEPTH */
    uint32_t dropped; /* pushes refused because the ring was full */
} uimk2_ring;

void uimk2_ring_init(uimk2_ring *r);

/* Copy e into the tail slot, then advance the tail. False (and one ERROR
 * log, dropped += 1) when the ring already holds QUEUE_DEPTH events. */
bool uimk2_ring_push(uimk2_ring *r, const uimk2_event *e);

/* Pointer to the oldest event, or NULL when empty. Valid until pop. */
uimk2_event *uimk2_ring_peek(uimk2_ring *r);

/* Advance the head past the oldest event. False when empty. */
bool uimk2_ring_pop(uimk2_ring *r);

uint32_t uimk2_ring_len(const uimk2_ring *r);

/* Name of a selector for logs and tests, "?" for anything else. One switch. */
const char *uimk2_event_sel_name(uimk2_event_sel sel);

/* Core A posts. Each is one push; the firmware adds the B wake-up. */
bool uimk2_post_press(uimk2_ring *r, int x, int y);
bool uimk2_post_volume(uimk2_ring *r, int new_val);
bool uimk2_post_screen_on(uimk2_ring *r);
bool uimk2_post_screen_off(uimk2_ring *r);

/* Core B pushes, from the handler and the schedulers. */
bool uimk2_push_toggle(uimk2_ring *r);
bool uimk2_push_update_render_draw(uimk2_ring *r);
bool uimk2_push_redraw(uimk2_ring *r, int attempt);
bool uimk2_push_clock(uimk2_ring *r);
bool uimk2_push_player_poll(uimk2_ring *r);

#endif /* UIMK2_EVENT_H */
