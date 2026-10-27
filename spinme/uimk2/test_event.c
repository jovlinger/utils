/* Host tests for the uimk2 Core B event ring.
 *
 * The handler below is a model of B: one switch on the selector, state in a
 * plain struct. It is enough to replay the sample sequences in
 * spinme/DESIGN.md "Sample queue". The full-ring test prints one expected
 * "ERROR: event ring full" line on stderr.
 */
#include "uimk2_event.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                        \
    do {                                                                   \
        checks++;                                                          \
        if (!(cond)) {                                                     \
            failures++;                                                    \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__,         \
                    __LINE__, #cond);                                      \
        }                                                                  \
    } while (0)

/* ---- a model of Core B ---- */

#define BUTTON_X 100
#define BUTTON_Y 8
#define BUTTON_W 160
#define BUTTON_H 32

typedef struct {
    int desired;
    bool backlight;
    bool playing;
    int presses;
    int toggles;
    int polls;
    int renders;
    int clocks;
    int last_attempt;
    uint8_t handled[64];
    uint32_t nhandled;
} model;

static void model_init(model *m) {
    memset(m, 0, sizeof *m);
}

static bool hit_button(int x, int y) {
    return x >= BUTTON_X && y >= BUTTON_Y && x < BUTTON_X + BUTTON_W &&
           y < BUTTON_Y + BUTTON_H;
}

/* The event handler: one switch on the selector. The event pointer is a
 * slot in the ring, still owned, so the handler may push without the
 * pointer going stale. */
static void handle(model *m, uimk2_ring *r, const uimk2_event *e) {
    if (m->nhandled < sizeof m->handled) {
        m->handled[m->nhandled++] = e->selector;
    }
    switch ((uimk2_event_sel)e->selector) {
    case UIMK2_EV_PRESS:
        m->presses++;
        if (hit_button(e->u.press.x, e->u.press.y)) {
            (void)uimk2_push_toggle(r);
        }
        break;
    case UIMK2_EV_VOLUME:
        m->desired = e->u.volume.new_val;
        break;
    case UIMK2_EV_TOGGLE:
        m->toggles++;
        m->playing = !m->playing;
        break;
    case UIMK2_EV_SCREEN_ON:
        m->backlight = true;
        break;
    case UIMK2_EV_SCREEN_OFF:
        m->backlight = false;
        break;
    case UIMK2_EV_UPDATE_RENDER_DRAW:
        m->renders++;
        break;
    case UIMK2_EV_REDRAW:
        m->last_attempt = e->u.redraw.attempt;
        break;
    case UIMK2_EV_CLOCK:
        m->clocks++;
        break;
    case UIMK2_EV_PLAYER_POLL:
        m->polls++;
        break;
    case UIMK2_EV_NONE:
    case UIMK2_EV_COUNT:
        break;
    }
}

/* One pass of the B loop body: peek, handle, pop. False when idle. */
static bool step(model *m, uimk2_ring *r) {
    uimk2_event *e = uimk2_ring_peek(r);
    if (e == NULL) {
        return false;
    }
    handle(m, r, e);
    CHECK(uimk2_ring_pop(r));
    return true;
}

static void drain(model *m, uimk2_ring *r) {
    while (step(m, r)) {
    }
}

/* Selector of the i-th queued event, counting from the head. */
static uimk2_event_sel sel_at(const uimk2_ring *r, uint32_t i) {
    return (uimk2_event_sel)r->slot[(r->head + i) % QUEUE_DEPTH].selector;
}

static const uimk2_event *ev_at(const uimk2_ring *r, uint32_t i) {
    return &r->slot[(r->head + i) % QUEUE_DEPTH];
}

/* ---- tests ---- */

static void test_init_empty(void) {
    uimk2_ring r;
    uimk2_ring_init(&r);
    CHECK(uimk2_ring_len(&r) == 0);
    CHECK(uimk2_ring_peek(&r) == NULL);
    CHECK(!uimk2_ring_pop(&r));
    CHECK(r.dropped == 0);
    CHECK(QUEUE_DEPTH == 8u);
}

static void test_event_shape(void) {
    uimk2_event e;
    CHECK(sizeof e.selector == 1);
    CHECK(sizeof e <= 3 * sizeof(int));
    CHECK(UIMK2_EV_NONE == 0);
    CHECK(UIMK2_EV_COUNT <= 255);
}

static void test_fifo_order(void) {
    uimk2_ring r;
    uimk2_ring_init(&r);
    CHECK(uimk2_push_clock(&r));
    CHECK(uimk2_post_press(&r, 1, 2));
    CHECK(uimk2_push_redraw(&r, 3));
    CHECK(uimk2_ring_len(&r) == 3);
    CHECK(uimk2_ring_peek(&r)->selector == UIMK2_EV_CLOCK);
    CHECK(uimk2_ring_pop(&r));
    CHECK(uimk2_ring_peek(&r)->selector == UIMK2_EV_PRESS);
    CHECK(uimk2_ring_peek(&r)->u.press.x == 1);
    CHECK(uimk2_ring_peek(&r)->u.press.y == 2);
    CHECK(uimk2_ring_pop(&r));
    CHECK(uimk2_ring_peek(&r)->selector == UIMK2_EV_REDRAW);
    CHECK(uimk2_ring_peek(&r)->u.redraw.attempt == 3);
    CHECK(uimk2_ring_pop(&r));
    CHECK(uimk2_ring_peek(&r) == NULL);
    CHECK(!uimk2_ring_pop(&r));
}

static void test_full_ring_drops(void) {
    uimk2_ring r;
    uint32_t i;
    uimk2_ring_init(&r);
    CHECK(uimk2_post_volume(&r, 7));
    for (i = 1; i < QUEUE_DEPTH; i++) {
        CHECK(uimk2_push_toggle(&r));
    }
    CHECK(uimk2_ring_len(&r) == QUEUE_DEPTH);
    fprintf(stderr, "(expected one ERROR line follows)\n");
    CHECK(!uimk2_post_volume(&r, 9)); /* the one that did not fit */
    CHECK(r.dropped == 1);
    CHECK(uimk2_ring_len(&r) == QUEUE_DEPTH);
    /* nothing in the ring was replaced or moved */
    CHECK(sel_at(&r, 0) == UIMK2_EV_VOLUME && ev_at(&r, 0)->u.volume.new_val == 7);
    for (i = 1; i < QUEUE_DEPTH; i++) {
        CHECK(sel_at(&r, i) == UIMK2_EV_TOGGLE);
    }
    /* pop one, then the push lands at the tail */
    CHECK(uimk2_ring_pop(&r));
    CHECK(uimk2_post_volume(&r, 9));
    CHECK(uimk2_ring_len(&r) == QUEUE_DEPTH);
    CHECK(sel_at(&r, QUEUE_DEPTH - 1u) == UIMK2_EV_VOLUME);
    CHECK(ev_at(&r, QUEUE_DEPTH - 1u)->u.volume.new_val == 9);
    CHECK(r.dropped == 1);
}

static void test_wraparound_keeps_order(void) {
    uimk2_ring r;
    model m;
    int i;
    uimk2_ring_init(&r);
    model_init(&m);
    /* Walk head and tail around the ring several times with two in flight. */
    for (i = 0; i < 3 * (int)QUEUE_DEPTH; i++) {
        CHECK(uimk2_post_volume(&r, i));
        CHECK(uimk2_post_volume(&r, i + 1000));
        CHECK(uimk2_ring_len(&r) == 2);
        CHECK(uimk2_ring_peek(&r)->u.volume.new_val == i);
        CHECK(uimk2_ring_pop(&r));
        CHECK(uimk2_ring_peek(&r)->u.volume.new_val == i + 1000);
        CHECK(uimk2_ring_pop(&r));
    }
    CHECK(uimk2_ring_len(&r) == 0);
    CHECK(r.dropped == 0);
    /* Fill across the seam and drain in order. */
    for (i = 0; i < (int)QUEUE_DEPTH; i++) {
        CHECK(uimk2_post_volume(&r, 100 + i));
    }
    for (i = 0; i < (int)QUEUE_DEPTH; i++) {
        CHECK(uimk2_ring_peek(&r)->u.volume.new_val == 100 + i);
        CHECK(uimk2_ring_pop(&r));
    }
    CHECK(uimk2_ring_peek(&r) == NULL);
}

static void test_peek_handle_pop_ownership(void) {
    uimk2_ring r;
    uimk2_event *e;
    uimk2_event *again;
    uimk2_ring_init(&r);
    CHECK(uimk2_post_press(&r, 180, 20));
    e = uimk2_ring_peek(&r);
    CHECK(e != NULL);
    CHECK(e == &r.slot[0]); /* a pointer into the ring, not a copy */
    /* Peek is idempotent until pop. */
    again = uimk2_ring_peek(&r);
    CHECK(again == e);
    /* A push during handling does not disturb the owned slot. */
    CHECK(uimk2_push_toggle(&r));
    CHECK(uimk2_post_volume(&r, 5));
    CHECK(uimk2_ring_peek(&r) == e);
    CHECK(e->selector == UIMK2_EV_PRESS);
    CHECK(e->u.press.x == 180 && e->u.press.y == 20);
    CHECK(uimk2_ring_len(&r) == 3);
    /* Only pop releases it. */
    CHECK(uimk2_ring_pop(&r));
    CHECK(uimk2_ring_peek(&r) != e);
    CHECK(uimk2_ring_peek(&r)->selector == UIMK2_EV_TOGGLE);
}

/* DESIGN sample: a detent at t = 0 with the screen off. A pools the rotation
 * and posts screen_on plus one volume message. */
static void test_sample_wake_detent(void) {
    uimk2_ring r;
    model m;
    uimk2_ring_init(&r);
    model_init(&m);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_post_volume(&r, 41));
    CHECK(uimk2_ring_len(&r) == 2);
    CHECK(sel_at(&r, 0) == UIMK2_EV_SCREEN_ON);
    CHECK(sel_at(&r, 1) == UIMK2_EV_VOLUME);
    CHECK(ev_at(&r, 1)->u.volume.new_val == 41);
    CHECK(!m.backlight);
    CHECK(step(&m, &r));
    CHECK(m.backlight);
    CHECK(m.desired == 0);
    CHECK(step(&m, &r));
    CHECK(m.desired == 41);
    CHECK(!step(&m, &r));
    /* Render then pushes redraw(0). */
    CHECK(uimk2_push_redraw(&r, 0));
    CHECK(uimk2_ring_len(&r) == 1 && sel_at(&r, 0) == UIMK2_EV_REDRAW);
    CHECK(ev_at(&r, 0)->u.redraw.attempt == 0);
    drain(&m, &r);
    CHECK(m.last_attempt == 0);
    CHECK(m.nhandled == 3);
    CHECK(m.handled[0] == UIMK2_EV_SCREEN_ON);
    CHECK(m.handled[1] == UIMK2_EV_VOLUME);
    CHECK(m.handled[2] == UIMK2_EV_REDRAW);
}

/* DESIGN sample: the poll scheduler fires, then A messages 42 and 43. The
 * ring holds values, so 43 does not replace 42. */
static void test_sample_volume_behind_poll(void) {
    uimk2_ring r;
    model m;
    uimk2_ring_init(&r);
    model_init(&m);
    CHECK(uimk2_push_player_poll(&r));
    CHECK(uimk2_post_volume(&r, 42));
    CHECK(uimk2_post_volume(&r, 43));
    CHECK(uimk2_ring_len(&r) == 3);
    CHECK(sel_at(&r, 0) == UIMK2_EV_PLAYER_POLL);
    CHECK(sel_at(&r, 1) == UIMK2_EV_VOLUME && ev_at(&r, 1)->u.volume.new_val == 42);
    CHECK(sel_at(&r, 2) == UIMK2_EV_VOLUME && ev_at(&r, 2)->u.volume.new_val == 43);
    CHECK(step(&m, &r));
    CHECK(m.polls == 1 && m.desired == 0);
    CHECK(step(&m, &r));
    CHECK(m.desired == 42);
    CHECK(step(&m, &r));
    CHECK(m.desired == 43);
    CHECK(!step(&m, &r));
    /* A second poll tick is another event; two polls are idempotent. */
    CHECK(uimk2_push_player_poll(&r));
    CHECK(uimk2_push_player_poll(&r));
    drain(&m, &r);
    CHECK(m.polls == 3);
    CHECK(m.desired == 43);
}

/* DESIGN sample: touch at (180, 20) and a second touch before the first is
 * handled. Both presses are kept. Each hit on the transport button makes B
 * push toggle behind whatever is already queued. */
static void test_sample_two_presses(void) {
    uimk2_ring r;
    model m;
    uimk2_event *e;
    uimk2_ring_init(&r);
    model_init(&m);
    CHECK(uimk2_post_press(&r, 180, 20));
    CHECK(uimk2_post_press(&r, 180, 22));
    CHECK(uimk2_ring_len(&r) == 2);
    CHECK(ev_at(&r, 0)->u.press.x == 180 && ev_at(&r, 0)->u.press.y == 20);
    CHECK(ev_at(&r, 1)->u.press.x == 180 && ev_at(&r, 1)->u.press.y == 22);

    /* Handle the first press by hand to watch the toggle land. */
    e = uimk2_ring_peek(&r);
    CHECK(e != NULL && e->selector == UIMK2_EV_PRESS);
    handle(&m, &r, e);
    CHECK(uimk2_ring_len(&r) == 3);
    CHECK(sel_at(&r, 0) == UIMK2_EV_PRESS); /* still owned */
    CHECK(sel_at(&r, 1) == UIMK2_EV_PRESS);
    CHECK(sel_at(&r, 2) == UIMK2_EV_TOGGLE);
    CHECK(m.toggles == 0);
    CHECK(uimk2_ring_pop(&r));

    drain(&m, &r);
    CHECK(m.presses == 2);
    CHECK(m.toggles == 2);
    CHECK(!m.playing); /* two toggles cancel */
    CHECK(m.nhandled == 4);
    CHECK(m.handled[0] == UIMK2_EV_PRESS);
    CHECK(m.handled[1] == UIMK2_EV_PRESS);
    CHECK(m.handled[2] == UIMK2_EV_TOGGLE);
    CHECK(m.handled[3] == UIMK2_EV_TOGGLE);

    /* A miss is just a press; nothing is appended. */
    CHECK(uimk2_post_press(&r, 0, 0));
    drain(&m, &r);
    CHECK(m.presses == 3);
    CHECK(m.toggles == 2);
}

static void test_a_side_posts_only(void) {
    uimk2_ring r;
    model m;
    uimk2_ring_init(&r);
    model_init(&m);
    CHECK(uimk2_post_screen_on(&r));
    CHECK(uimk2_post_press(&r, 3, 4));
    CHECK(uimk2_post_volume(&r, 12));
    CHECK(uimk2_post_screen_off(&r));
    CHECK(uimk2_ring_len(&r) == 4);
    CHECK(sel_at(&r, 0) == UIMK2_EV_SCREEN_ON);
    CHECK(sel_at(&r, 1) == UIMK2_EV_PRESS);
    CHECK(sel_at(&r, 2) == UIMK2_EV_VOLUME);
    CHECK(sel_at(&r, 3) == UIMK2_EV_SCREEN_OFF);
    /* selector-only events carry a zeroed payload */
    CHECK(ev_at(&r, 0)->u.press.x == 0 && ev_at(&r, 0)->u.press.y == 0);
    drain(&m, &r);
    CHECK(!m.backlight);
    CHECK(m.desired == 12);
    CHECK(m.presses == 1);
}

static void test_b_side_pushes(void) {
    uimk2_ring r;
    model m;
    uimk2_ring_init(&r);
    model_init(&m);
    CHECK(uimk2_push_update_render_draw(&r));
    CHECK(uimk2_push_clock(&r));
    CHECK(uimk2_push_redraw(&r, 4));
    CHECK(uimk2_push_toggle(&r));
    CHECK(uimk2_push_player_poll(&r));
    CHECK(uimk2_ring_len(&r) == 5);
    drain(&m, &r);
    CHECK(m.renders == 1);
    CHECK(m.clocks == 1);
    CHECK(m.last_attempt == 4);
    CHECK(m.toggles == 1 && m.playing);
    CHECK(m.polls == 1);
}

static void test_toggle_appends_never_coalesces(void) {
    uimk2_ring r;
    model m;
    uimk2_ring_init(&r);
    model_init(&m);
    CHECK(uimk2_push_toggle(&r));
    CHECK(uimk2_push_toggle(&r));
    CHECK(uimk2_push_toggle(&r));
    CHECK(uimk2_ring_len(&r) == 3);
    drain(&m, &r);
    CHECK(m.toggles == 3);
    CHECK(m.playing);
}

static void test_selector_names(void) {
    int i, j;
    const char *names[UIMK2_EV_COUNT];
    for (i = 0; i < (int)UIMK2_EV_COUNT; i++) {
        names[i] = uimk2_event_sel_name((uimk2_event_sel)i);
        CHECK(names[i] != NULL);
        CHECK(strcmp(names[i], "?") != 0);
        for (j = 0; j < i; j++) {
            CHECK(strcmp(names[i], names[j]) != 0);
        }
    }
    CHECK(strcmp(uimk2_event_sel_name(UIMK2_EV_COUNT), "?") == 0);
    CHECK(strcmp(uimk2_event_sel_name((uimk2_event_sel)200), "?") == 0);
    CHECK(strcmp(uimk2_event_sel_name(UIMK2_EV_VOLUME), "volume") == 0);
    CHECK(strcmp(uimk2_event_sel_name(UIMK2_EV_UPDATE_RENDER_DRAW),
                 "update_render_draw") == 0);
}

int main(void) {
    test_init_empty();
    test_event_shape();
    test_fifo_order();
    test_full_ring_drops();
    test_wraparound_keeps_order();
    test_peek_handle_pop_ownership();
    test_sample_wake_detent();
    test_sample_volume_behind_poll();
    test_sample_two_presses();
    test_a_side_posts_only();
    test_b_side_pushes();
    test_toggle_appends_never_coalesces();
    test_selector_names();
    printf("test_event: %d checks, %d failures\n", checks, failures);
    return failures ? EXIT_FAILURE : EXIT_SUCCESS;
}
