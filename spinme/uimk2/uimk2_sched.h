/* uimk2 scheduler model: the work queue (network core) and the UI queue
 * (display core), plus the awake / poll-backoff clocks.
 *
 * Host-testable, no FreeRTOS. The firmware wraps these in its own locking.
 *
 * Work queue (depth 8): Poll, SetVolume(absolute), Toggle. A new SetVolume or
 * Poll replaces a queued one in place (the slot does not move). Toggle never
 * coalesces.
 *
 * UI queue (depth 8): Knob, Touch, Snapshot, Scroll(viewport, dx, dy). A
 * Scroll for an already queued viewport sums into that slot; a 0,0 sum removes
 * the slot. Scroll is never pushed onto the work queue.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_SCHED_H
#define UIMK2_SCHED_H

#include <stdbool.h>
#include <stdint.h>

#define UIMK2_SCHED_DEPTH 8u
#define UIMK2_SCHED_SCREEN_ON_MS 30000u
#define UIMK2_SCHED_POLL_GAP_MIN_MS 1000u
#define UIMK2_SCHED_POLL_GAP_MAX_MS 16000u

typedef enum {
    UIMK2_WORK_POLL = 0,
    UIMK2_WORK_SET_VOLUME,
    UIMK2_WORK_TOGGLE
} uimk2_work_kind;

typedef struct {
    uimk2_work_kind kind;
    int32_t volume; /* SetVolume only */
} uimk2_work_item;

typedef enum {
    UIMK2_UI_KNOB = 0,
    UIMK2_UI_TOUCH,
    UIMK2_UI_SNAPSHOT,
    UIMK2_UI_SCROLL
} uimk2_ui_kind;

typedef struct {
    uimk2_ui_kind kind;
    int32_t delta;    /* Knob */
    int32_t x, y;     /* Touch */
    int32_t viewport; /* Scroll */
    int32_t dx, dy;   /* Scroll */
} uimk2_ui_item;

typedef struct {
    uimk2_work_item work[UIMK2_SCHED_DEPTH];
    uint32_t work_len;
    uimk2_ui_item ui[UIMK2_SCHED_DEPTH];
    uint32_t ui_len;

    bool scrolling; /* view flag; default false (follow) */

    bool awake;
    uint32_t poll_gap_ms;
    uint32_t last_activity; /* ms */
    uint32_t last_poll;     /* ms */
} uimk2_sched;

void uimk2_sched_init(uimk2_sched *s);

/* Work queue. post: true on append or replace, false when full and not a
 * replace. pop: oldest item, false when empty. */
bool uimk2_sched_post_poll(uimk2_sched *s);
bool uimk2_sched_post_volume(uimk2_sched *s, int32_t volume);
bool uimk2_sched_post_toggle(uimk2_sched *s);
bool uimk2_sched_work_pop(uimk2_sched *s, uimk2_work_item *out);

/* UI queue. */
bool uimk2_sched_post_knob(uimk2_sched *s, int32_t delta);
bool uimk2_sched_post_scroll(uimk2_sched *s, int32_t viewport, int32_t dx,
                             int32_t dy);
bool uimk2_sched_ui_pop(uimk2_sched *s, uimk2_ui_item *out);

/* A decoded detent. Scrolling: post Scroll(dx, dy) for viewport. Otherwise
 * post SetVolume(volume). Restarts the clocks. Returns the post result. */
bool uimk2_sched_detent(uimk2_sched *s, uint32_t now_ms, int32_t dx,
                        int32_t dy, int32_t volume, int32_t viewport);

/* Enqueue Touch and restart the clocks. Returns the post result. */
bool uimk2_sched_touch(uimk2_sched *s, uint32_t now_ms, int32_t x, int32_t y);

/* Enqueue Snapshot. Clocks, awake and poll_gap are untouched. */
bool uimk2_sched_snapshot(uimk2_sched *s);

/* Advance the clocks. True when a Poll was posted by this tick. */
bool uimk2_sched_tick(uimk2_sched *s, uint32_t now_ms);

#endif /* UIMK2_SCHED_H */
