/* Core B scheduler list on the uimk2_event ring.
 *
 * Permanent slots: update_render_draw (UPDATE_RENDER_EVERY, while the
 * backlight is on), clock (one logical second), and player poll
 * (POLL_EVERY_START, doubling after each fire up to POLL_EVERY_MAX,
 * only while armed). One-offs live in a second list, packed to the
 * front and zero-terminated: screen-off, and a redraw retry when
 * busy-by-core-A. Each slot does one thing: it pushes one event.
 * Dispatch is a switch on the selector.
 *
 * A slot is due when last_run + every < now. last_run is set to now
 * before the push. uimk2_sched.h remains the follow-view work queue.
 *
 * B owns desired volume and the player mode. A press is only (x, y);
 * B hit-tests. A transport shape enqueues Toggle, and enqueues Poll
 * when the poll scheduler was already armed.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_HOST_H
#define UIMK2_HOST_H

#include <stdbool.h>
#include <stdint.h>

#include "uimk2_config.h"
#include "uimk2_event.h"
#include "uimk2_zlist.h"

/* Clock period: one logical second, in CLOCK_RES ticks. */
#define UIMK2_HOST_CLOCK_EVERY CLOCKS_PER_SEC_TICKS

/* Usable one-off slots. once[UIMK2_HOST_ONCE] stays the zero terminator. */
#define UIMK2_HOST_ONCE 4u

typedef enum {
    UIMK2_SCH_NONE = 0, /* empty slot, and the one-off terminator */
    UIMK2_SCH_UPDATE_RENDER_DRAW,
    UIMK2_SCH_CLOCK,
    UIMK2_SCH_PLAYER_POLL,
    UIMK2_SCH_SCREEN_OFF,
    UIMK2_SCH_REDRAW
} uimk2_sch_sel;

enum {
    UIMK2_HOST_PERM_RENDER = 0,
    UIMK2_HOST_PERM_CLOCK = 1,
    UIMK2_HOST_PERM_POLL = 2,
    UIMK2_HOST_PERM_COUNT = 3
};

typedef struct {
    uint8_t selector; /* uimk2_sch_sel; 0 means empty */
    uint32_t last_run;
    uint32_t every;
    uint32_t expire_by; /* one-offs: absolute tick; often last_run + every */
    int attempt;        /* redraw retry */
} uimk2_host_slot;

typedef struct {
    uimk2_host_slot perm[UIMK2_HOST_PERM_COUNT];
    uimk2_host_slot once[UIMK2_HOST_ONCE + 1u];
    uimk2_ring *ring;
    uimk2_zlist *zlist; /* NULL skips paint, hit-test, and redraw hold */
    bool backlight;
    bool poll_enabled;
    int desired; /* B's volume; A's pooled clicks land here */
    bool playing;
    uint32_t now;
    int32_t clock_sec;
    uint32_t clock_tick;
    uint32_t renders;
    uint32_t polls;
    uint32_t clocks;
    uint32_t toggles;
    int last_attempt;
} uimk2_host;

/* Permanent slots anchored at now. Backlight off, poll disarmed.
 * ring is required. Bind a zlist after each uimk2_zlist_build. */
void uimk2_host_init(uimk2_host *h, uimk2_ring *ring, uint32_t now);

/* Remember z and ask it to hold busy redraws for the one-off list.
 * Build clears that flag; bind again after a rebuild. */
void uimk2_host_bind(uimk2_host *h, uimk2_zlist *z);

/* Append one one-off. last_run is now. False when sel is empty or the
 * list is full (ERROR, the new slot is not stored). */
bool uimk2_host_arm_once(uimk2_host *h, uint8_t selector, uint32_t now,
                         uint32_t every, uint32_t expire_by, int attempt);

/* Peek, handle, pop. False when the ring is empty. now is the clock
 * the handler and any armed one-off see. */
bool uimk2_host_step(uimk2_host *h, uint32_t now);

/* Run every due scheduler. Returns the wait, in ticks, until the next
 * due point (the first now at which last_run + every < now). */
uint32_t uimk2_host_run(uimk2_host *h, uint32_t now);

#endif /* UIMK2_HOST_H */
