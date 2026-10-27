/* uimk2 Core B event ring. See uimk2_event.h. */
#include "uimk2_event.h"

#include <string.h>

/* ERROR log for a dropped push. A board file may define its own before
 * including this translation unit; the host default goes to stderr. */
#ifndef UIMK2_EVENT_LOG_ERROR
#include <stdio.h>
#define UIMK2_EVENT_LOG_ERROR(what)                                           \
    fprintf(stderr, "ERROR: event ring full, dropped %s\n", (what))
#endif

void uimk2_ring_init(uimk2_ring *r) {
    memset(r, 0, sizeof *r);
}

bool uimk2_ring_push(uimk2_ring *r, const uimk2_event *e) {
    if (r->len >= QUEUE_DEPTH) {
        r->dropped++;
        UIMK2_EVENT_LOG_ERROR(uimk2_event_sel_name((uimk2_event_sel)e->selector));
        return false;
    }
    r->slot[r->tail] = *e;
    r->tail = (r->tail + 1u) % QUEUE_DEPTH;
    r->len++;
    return true;
}

uimk2_event *uimk2_ring_peek(uimk2_ring *r) {
    if (r->len == 0) {
        return NULL;
    }
    return &r->slot[r->head];
}

bool uimk2_ring_pop(uimk2_ring *r) {
    if (r->len == 0) {
        return false;
    }
    r->head = (r->head + 1u) % QUEUE_DEPTH;
    r->len--;
    return true;
}

uint32_t uimk2_ring_len(const uimk2_ring *r) {
    return r->len;
}

const char *uimk2_event_sel_name(uimk2_event_sel sel) {
    switch (sel) {
    case UIMK2_EV_NONE:
        return "none";
    case UIMK2_EV_PRESS:
        return "press";
    case UIMK2_EV_VOLUME:
        return "volume";
    case UIMK2_EV_TOGGLE:
        return "toggle";
    case UIMK2_EV_SCREEN_ON:
        return "screen_on";
    case UIMK2_EV_SCREEN_OFF:
        return "screen_off";
    case UIMK2_EV_UPDATE_RENDER_DRAW:
        return "update_render_draw";
    case UIMK2_EV_REDRAW:
        return "redraw";
    case UIMK2_EV_CLOCK:
        return "clock";
    case UIMK2_EV_PLAYER_POLL:
        return "player_poll";
    case UIMK2_EV_COUNT:
        break;
    }
    return "?";
}

/* Build a selector-only event. The union is zeroed so a slot compares
 * cleanly in tests and dumps. */
static bool push_bare(uimk2_ring *r, uimk2_event_sel sel) {
    uimk2_event e;
    memset(&e, 0, sizeof e);
    e.selector = (uint8_t)sel;
    return uimk2_ring_push(r, &e);
}

/* ---- Core A posts ---- */

bool uimk2_post_press(uimk2_ring *r, int x, int y) {
    uimk2_event e;
    memset(&e, 0, sizeof e);
    e.selector = (uint8_t)UIMK2_EV_PRESS;
    e.u.press.x = x;
    e.u.press.y = y;
    return uimk2_ring_push(r, &e);
}

bool uimk2_post_volume(uimk2_ring *r, int new_val) {
    uimk2_event e;
    memset(&e, 0, sizeof e);
    e.selector = (uint8_t)UIMK2_EV_VOLUME;
    e.u.volume.new_val = new_val;
    return uimk2_ring_push(r, &e);
}

bool uimk2_post_screen_on(uimk2_ring *r) {
    return push_bare(r, UIMK2_EV_SCREEN_ON);
}

bool uimk2_post_screen_off(uimk2_ring *r) {
    return push_bare(r, UIMK2_EV_SCREEN_OFF);
}

/* ---- Core B pushes ---- */

bool uimk2_push_toggle(uimk2_ring *r) {
    return push_bare(r, UIMK2_EV_TOGGLE);
}

bool uimk2_push_update_render_draw(uimk2_ring *r) {
    return push_bare(r, UIMK2_EV_UPDATE_RENDER_DRAW);
}

bool uimk2_push_redraw(uimk2_ring *r, int attempt) {
    uimk2_event e;
    memset(&e, 0, sizeof e);
    e.selector = (uint8_t)UIMK2_EV_REDRAW;
    e.u.redraw.attempt = attempt;
    return uimk2_ring_push(r, &e);
}

bool uimk2_push_clock(uimk2_ring *r) {
    return push_bare(r, UIMK2_EV_CLOCK);
}

bool uimk2_push_player_poll(uimk2_ring *r) {
    return push_bare(r, UIMK2_EV_PLAYER_POLL);
}
