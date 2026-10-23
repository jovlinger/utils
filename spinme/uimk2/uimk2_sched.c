/* uimk2 scheduler model. See uimk2_sched.h. */
#include "uimk2_sched.h"

#include <string.h>

void uimk2_sched_init(uimk2_sched *s) {
    memset(s, 0, sizeof *s);
    s->scrolling = false;
    s->awake = true;
    s->poll_gap_ms = UIMK2_SCHED_POLL_GAP_MIN_MS;
    s->last_activity = 0;
    s->last_poll = 0;
}

/* ---- work queue ---- */

static bool work_append(uimk2_sched *s, uimk2_work_kind kind, int32_t volume) {
    if (s->work_len >= UIMK2_SCHED_DEPTH) {
        return false;
    }
    s->work[s->work_len].kind = kind;
    s->work[s->work_len].volume = volume;
    s->work_len++;
    return true;
}

/* Replace the first queued item of kind in place, if any. */
static bool work_replace(uimk2_sched *s, uimk2_work_kind kind,
                         int32_t volume) {
    uint32_t i;
    for (i = 0; i < s->work_len; i++) {
        if (s->work[i].kind == kind) {
            s->work[i].volume = volume;
            return true;
        }
    }
    return false;
}

bool uimk2_sched_post_poll(uimk2_sched *s) {
    if (work_replace(s, UIMK2_WORK_POLL, 0)) {
        return true;
    }
    return work_append(s, UIMK2_WORK_POLL, 0);
}

bool uimk2_sched_post_volume(uimk2_sched *s, int32_t volume) {
    if (work_replace(s, UIMK2_WORK_SET_VOLUME, volume)) {
        return true;
    }
    return work_append(s, UIMK2_WORK_SET_VOLUME, volume);
}

bool uimk2_sched_post_toggle(uimk2_sched *s) {
    return work_append(s, UIMK2_WORK_TOGGLE, 0);
}

bool uimk2_sched_work_pop(uimk2_sched *s, uimk2_work_item *out) {
    uint32_t i;
    if (s->work_len == 0) {
        return false;
    }
    *out = s->work[0];
    for (i = 1; i < s->work_len; i++) {
        s->work[i - 1] = s->work[i];
    }
    s->work_len--;
    return true;
}

/* ---- UI queue ---- */

static bool ui_append(uimk2_sched *s, const uimk2_ui_item *it) {
    if (s->ui_len >= UIMK2_SCHED_DEPTH) {
        return false;
    }
    s->ui[s->ui_len++] = *it;
    return true;
}

static void ui_remove(uimk2_sched *s, uint32_t idx) {
    uint32_t i;
    for (i = idx + 1; i < s->ui_len; i++) {
        s->ui[i - 1] = s->ui[i];
    }
    s->ui_len--;
}

bool uimk2_sched_post_knob(uimk2_sched *s, int32_t delta) {
    uimk2_ui_item it;
    memset(&it, 0, sizeof it);
    it.kind = UIMK2_UI_KNOB;
    it.delta = delta;
    return ui_append(s, &it);
}

bool uimk2_sched_post_scroll(uimk2_sched *s, int32_t viewport, int32_t dx,
                             int32_t dy) {
    uimk2_ui_item it;
    uint32_t i;
    for (i = 0; i < s->ui_len; i++) {
        if (s->ui[i].kind == UIMK2_UI_SCROLL &&
            s->ui[i].viewport == viewport) {
            s->ui[i].dx += dx;
            s->ui[i].dy += dy;
            if (s->ui[i].dx == 0 && s->ui[i].dy == 0) {
                ui_remove(s, i);
            }
            return true;
        }
    }
    memset(&it, 0, sizeof it);
    it.kind = UIMK2_UI_SCROLL;
    it.viewport = viewport;
    it.dx = dx;
    it.dy = dy;
    return ui_append(s, &it);
}

bool uimk2_sched_ui_pop(uimk2_sched *s, uimk2_ui_item *out) {
    if (s->ui_len == 0) {
        return false;
    }
    *out = s->ui[0];
    ui_remove(s, 0);
    return true;
}

/* ---- clocks ---- */

static void restart(uimk2_sched *s, uint32_t now_ms) {
    s->last_activity = now_ms;
    s->poll_gap_ms = UIMK2_SCHED_POLL_GAP_MIN_MS;
    if (!s->awake) {
        s->awake = true;
        (void)uimk2_sched_post_poll(s);
    }
    s->last_poll = now_ms;
}

bool uimk2_sched_detent(uimk2_sched *s, uint32_t now_ms, int32_t dx,
                        int32_t dy, int32_t volume, int32_t viewport) {
    bool ok;
    restart(s, now_ms);
    if (s->scrolling) {
        ok = uimk2_sched_post_scroll(s, viewport, dx, dy);
    } else {
        ok = uimk2_sched_post_volume(s, volume);
    }
    return ok;
}

bool uimk2_sched_touch(uimk2_sched *s, uint32_t now_ms, int32_t x, int32_t y) {
    uimk2_ui_item it;
    restart(s, now_ms);
    memset(&it, 0, sizeof it);
    it.kind = UIMK2_UI_TOUCH;
    it.x = x;
    it.y = y;
    return ui_append(s, &it);
}

bool uimk2_sched_snapshot(uimk2_sched *s) {
    uimk2_ui_item it;
    memset(&it, 0, sizeof it);
    it.kind = UIMK2_UI_SNAPSHOT;
    return ui_append(s, &it);
}

bool uimk2_sched_tick(uimk2_sched *s, uint32_t now_ms) {
    if (!s->awake) {
        return false;
    }
    if (now_ms - s->last_activity >= UIMK2_SCHED_SCREEN_ON_MS) {
        s->awake = false;
        return false;
    }
    if (now_ms - s->last_poll >= s->poll_gap_ms) {
        (void)uimk2_sched_post_poll(s);
        s->last_poll = now_ms;
        s->poll_gap_ms *= 2u;
        if (s->poll_gap_ms > UIMK2_SCHED_POLL_GAP_MAX_MS) {
            s->poll_gap_ms = UIMK2_SCHED_POLL_GAP_MAX_MS;
        }
        return true;
    }
    return false;
}
