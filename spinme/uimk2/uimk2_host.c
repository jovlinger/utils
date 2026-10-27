/* Core B scheduler list. See uimk2_host.h. */
#include "uimk2_host.h"

#include <stdio.h>
#include <string.h>

static bool sch_due(uint32_t last_run, uint32_t every, uint32_t now) {
    return last_run + every < now;
}

static uint32_t once_count(const uimk2_host *h) {
    uint32_t i;
    for (i = 0; i < UIMK2_HOST_ONCE; i++) {
        if (h->once[i].selector == (uint8_t)UIMK2_SCH_NONE) {
            return i;
        }
    }
    return UIMK2_HOST_ONCE;
}

static void once_remove(uimk2_host *h, uint32_t idx) {
    uint32_t n = once_count(h);
    if (idx >= n) {
        return;
    }
    /* Tail moves into the hole. Removing the tail zeroes that slot. */
    h->once[idx] = h->once[n - 1u];
    memset(&h->once[n - 1u], 0, sizeof h->once[0]);
}

static const char *sch_name(uint8_t sel) {
    switch ((uimk2_sch_sel)sel) {
    case UIMK2_SCH_NONE:
        return "none";
    case UIMK2_SCH_UPDATE_RENDER_DRAW:
        return "update_render_draw";
    case UIMK2_SCH_CLOCK:
        return "clock";
    case UIMK2_SCH_PLAYER_POLL:
        return "player_poll";
    case UIMK2_SCH_SCREEN_OFF:
        return "screen_off";
    case UIMK2_SCH_REDRAW:
        return "redraw";
    }
    return "?";
}

static bool push_sel(uimk2_host *h, uint8_t sel, int attempt) {
    if (h->ring == NULL) {
        return false;
    }
    switch ((uimk2_sch_sel)sel) {
    case UIMK2_SCH_UPDATE_RENDER_DRAW:
        return uimk2_push_update_render_draw(h->ring);
    case UIMK2_SCH_CLOCK:
        return uimk2_push_clock(h->ring);
    case UIMK2_SCH_PLAYER_POLL:
        return uimk2_push_player_poll(h->ring);
    case UIMK2_SCH_SCREEN_OFF:
        return uimk2_post_screen_off(h->ring);
    case UIMK2_SCH_REDRAW:
        return uimk2_push_redraw(h->ring, attempt);
    case UIMK2_SCH_NONE:
        break;
    }
    return false;
}

bool uimk2_host_arm_once(uimk2_host *h, uint8_t selector, uint32_t now,
                         uint32_t every, uint32_t expire_by, int attempt) {
    uint32_t n;
    uimk2_host_slot *slot;
    if (selector == (uint8_t)UIMK2_SCH_NONE) {
        return false;
    }
    n = once_count(h);
    if (n >= UIMK2_HOST_ONCE) {
        fprintf(stderr, "ERROR: one-off list full, dropped %s\n",
                sch_name(selector));
        return false;
    }
    slot = &h->once[n];
    memset(slot, 0, sizeof *slot);
    slot->selector = selector;
    slot->last_run = now;
    slot->every = every;
    slot->expire_by = expire_by;
    slot->attempt = attempt;
    return true;
}

/* Reset the live screen-off one-off, or append one. expire_by is
 * SCREEN_OFF_EVERY past now. A poll result does not call this. */
static void arm_screen_off(uimk2_host *h, uint32_t now) {
    uint32_t i;
    uint32_t n = once_count(h);
    for (i = 0; i < n; i++) {
        if (h->once[i].selector == (uint8_t)UIMK2_SCH_SCREEN_OFF) {
            h->once[i].last_run = now;
            h->once[i].every = SCREEN_OFF_EVERY;
            h->once[i].expire_by = now + SCREEN_OFF_EVERY;
            h->once[i].attempt = 0;
            return;
        }
    }
    (void)uimk2_host_arm_once(h, (uint8_t)UIMK2_SCH_SCREEN_OFF, now,
                              SCREEN_OFF_EVERY, now + SCREEN_OFF_EVERY, 0);
}

static void arm_poll(uimk2_host *h, uint32_t now) {
    uimk2_host_slot *s = &h->perm[UIMK2_HOST_PERM_POLL];
    h->poll_enabled = true;
    s->every = POLL_EVERY_START;
    s->last_run = now;
}

static void arm_held_redraw(uimk2_host *h) {
    uimk2_zlist *z = h->zlist;
    int attempt;
    if (z == NULL || !z->redraw_held) {
        return;
    }
    z->redraw_held = false;
    attempt = z->redraw_attempt;
    if (attempt >= (int)REDRAW_ATTEMPT_CAP) {
        fprintf(stderr, "ERROR: redraw busy at attempt cap %u\n",
                (unsigned)REDRAW_ATTEMPT_CAP);
    }
    (void)uimk2_host_arm_once(h, (uint8_t)UIMK2_SCH_REDRAW, h->now,
                              REDRAW_RETRY_EVERY, h->now + REDRAW_RETRY_EVERY,
                              attempt);
}

static void on_press(uimk2_host *h, const uimk2_event *e) {
    bool was_polling = h->poll_enabled;
    int hit = -1;
    arm_poll(h, h->now);
    arm_screen_off(h, h->now);
    if (h->zlist != NULL) {
        hit = uimk2_zlist_hit_test(h->zlist, e->u.press.x, e->u.press.y);
    }
    if (hit >= 0 && h->zlist->shape[hit].is_transport) {
        (void)uimk2_push_toggle(h->ring);
        /* Already awake: refresh the player now. A stopped poll is armed
         * above and waits out POLL_EVERY_START instead. */
        if (was_polling) {
            (void)uimk2_push_player_poll(h->ring);
        }
    }
}

static void handle(uimk2_host *h, const uimk2_event *e) {
    switch ((uimk2_event_sel)e->selector) {
    case UIMK2_EV_PRESS:
        on_press(h, e);
        break;
    case UIMK2_EV_VOLUME:
        h->desired = e->u.volume.new_val;
        arm_poll(h, h->now);
        arm_screen_off(h, h->now);
        break;
    case UIMK2_EV_TOGGLE:
        /* Local play/pause for drawing. The player command belongs here;
         * the host has no socket. */
        h->playing = !h->playing;
        h->toggles++;
        break;
    case UIMK2_EV_SCREEN_ON:
        h->backlight = true;
        arm_poll(h, h->now);
        arm_screen_off(h, h->now);
        h->perm[UIMK2_HOST_PERM_RENDER].last_run = h->now;
        (void)uimk2_push_update_render_draw(h->ring);
        break;
    case UIMK2_EV_SCREEN_OFF:
        h->backlight = false;
        h->poll_enabled = false;
        break;
    case UIMK2_EV_UPDATE_RENDER_DRAW:
        h->renders++;
        if (h->zlist != NULL) {
            /* Global millis into the zlist so SCROLL can read it. */
            h->clock_tick = h->now;
            h->clock_sec = (int32_t)(h->now / CLOCKS_PER_SEC_TICKS);
            uimk2_zlist_set_clock(h->zlist, h->clock_sec, h->clock_tick);
            h->zlist->hold_redraw = true;
            uimk2_zlist_update_render_draw(h->zlist);
            arm_held_redraw(h);
        }
        break;
    case UIMK2_EV_REDRAW:
        h->last_attempt = e->u.redraw.attempt;
        if (h->zlist != NULL) {
            h->zlist->hold_redraw = true;
            uimk2_zlist_redraw(h->zlist, e->u.redraw.attempt);
            arm_held_redraw(h);
        }
        break;
    case UIMK2_EV_CLOCK:
        h->clocks++;
        h->clock_tick = h->now;
        h->clock_sec = (int32_t)(h->now / CLOCKS_PER_SEC_TICKS);
        if (h->zlist != NULL) {
            uimk2_zlist_set_clock(h->zlist, h->clock_sec, h->clock_tick);
        }
        break;
    case UIMK2_EV_PLAYER_POLL:
        h->polls++;
        break;
    case UIMK2_EV_NONE:
    case UIMK2_EV_COUNT:
        break;
    }
}

bool uimk2_host_step(uimk2_host *h, uint32_t now) {
    uimk2_event *e;
    h->now = now;
    if (h->ring == NULL) {
        return false;
    }
    e = uimk2_ring_peek(h->ring);
    if (e == NULL) {
        return false;
    }
    handle(h, e);
    return uimk2_ring_pop(h->ring);
}

static bool perm_live(const uimk2_host *h, const uimk2_host_slot *s) {
    if (s->selector == (uint8_t)UIMK2_SCH_UPDATE_RENDER_DRAW) {
        return h->backlight;
    }
    if (s->selector == (uint8_t)UIMK2_SCH_PLAYER_POLL) {
        return h->poll_enabled;
    }
    return s->selector != (uint8_t)UIMK2_SCH_NONE;
}

static void bump_poll(uimk2_host_slot *s) {
    if (s->every <= POLL_EVERY_MAX / 2u) {
        s->every *= 2u;
    } else {
        s->every = POLL_EVERY_MAX;
    }
    if (s->every > POLL_EVERY_MAX) {
        s->every = POLL_EVERY_MAX;
    }
}

static void run_perm(uimk2_host *h, uint32_t now) {
    uint32_t i;
    for (i = 0; i < (uint32_t)UIMK2_HOST_PERM_COUNT; i++) {
        uimk2_host_slot *s = &h->perm[i];
        if (!perm_live(h, s)) {
            continue;
        }
        if (!sch_due(s->last_run, s->every, now)) {
            continue;
        }
        s->last_run = now;
        (void)push_sel(h, s->selector, 0);
        if (s->selector == (uint8_t)UIMK2_SCH_PLAYER_POLL) {
            bump_poll(s);
        }
    }
}

static void run_once(uimk2_host *h, uint32_t now) {
    uint32_t i = 0;
    while (i < UIMK2_HOST_ONCE && h->once[i].selector != (uint8_t)UIMK2_SCH_NONE) {
        uimk2_host_slot *s = &h->once[i];
        if (sch_due(s->last_run, s->every, now)) {
            uint8_t sel = s->selector;
            int attempt = s->attempt;
            uint32_t expire = s->expire_by;
            s->last_run = now;
            (void)push_sel(h, sel, attempt);
            if (now >= expire) {
                once_remove(h, i);
                continue;
            }
        } else if (now > s->expire_by) {
            once_remove(h, i);
            continue;
        }
        i++;
    }
}

/* Ticks until last_run + every < now becomes true. */
static uint32_t ticks_until(uint32_t last_run, uint32_t every, uint32_t now) {
    if (sch_due(last_run, every, now)) {
        return 0;
    }
    return (last_run + every - now) + 1u;
}

static void consider(uint32_t *best, uint32_t last_run, uint32_t every,
                     uint32_t now) {
    uint32_t wait = ticks_until(last_run, every, now);
    if (wait < *best) {
        *best = wait;
    }
}

static uint32_t next_delay(const uimk2_host *h, uint32_t now) {
    uint32_t best = UINT32_MAX;
    uint32_t i;
    for (i = 0; i < (uint32_t)UIMK2_HOST_PERM_COUNT; i++) {
        const uimk2_host_slot *s = &h->perm[i];
        if (!perm_live(h, s)) {
            continue;
        }
        consider(&best, s->last_run, s->every, now);
    }
    for (i = 0; i < UIMK2_HOST_ONCE; i++) {
        const uimk2_host_slot *s = &h->once[i];
        if (s->selector == (uint8_t)UIMK2_SCH_NONE) {
            break;
        }
        consider(&best, s->last_run, s->every, now);
    }
    return best;
}

void uimk2_host_init(uimk2_host *h, uimk2_ring *ring, uint32_t now) {
    memset(h, 0, sizeof *h);
    h->ring = ring;
    h->now = now;
    h->perm[UIMK2_HOST_PERM_RENDER].selector =
        (uint8_t)UIMK2_SCH_UPDATE_RENDER_DRAW;
    h->perm[UIMK2_HOST_PERM_RENDER].every = UPDATE_RENDER_EVERY;
    h->perm[UIMK2_HOST_PERM_RENDER].last_run = now;
    h->perm[UIMK2_HOST_PERM_CLOCK].selector = (uint8_t)UIMK2_SCH_CLOCK;
    h->perm[UIMK2_HOST_PERM_CLOCK].every = UIMK2_HOST_CLOCK_EVERY;
    h->perm[UIMK2_HOST_PERM_CLOCK].last_run = now;
    h->perm[UIMK2_HOST_PERM_POLL].selector = (uint8_t)UIMK2_SCH_PLAYER_POLL;
    h->perm[UIMK2_HOST_PERM_POLL].every = POLL_EVERY_START;
    h->perm[UIMK2_HOST_PERM_POLL].last_run = now;
}

void uimk2_host_bind(uimk2_host *h, uimk2_zlist *z) {
    if (h->zlist != NULL && h->zlist != z) {
        h->zlist->hold_redraw = false;
        h->zlist->redraw_held = false;
    }
    h->zlist = z;
    if (z != NULL) {
        z->hold_redraw = true;
    }
}

uint32_t uimk2_host_run(uimk2_host *h, uint32_t now) {
    h->now = now;
    run_perm(h, now);
    run_once(h, now);
    return next_delay(h, now);
}
