#include "ta_draw_events.h"

#include "ta_draw_glass.h"
#include "ta_net_http_event.h"
#include "ta_registry.h"

#include <string.h>

static ta_draw_stats_t g_stats;
static ta_queue_t *g_q;
/* Draw-originated ControlEvents share one conversation counter. */
static ta_session_id_t g_session = 0x100;
/* SET_TEXT reassembly: one string in flight per field. */
static char g_text_buf[TA_DRAW_TEXT_N][TA_GLASS_TEXT_MAX + 1];
static size_t g_text_len[TA_DRAW_TEXT_N];

void ta_draw_reset(void) {
    memset(&g_stats, 0, sizeof(g_stats));
    g_q = NULL;
    g_session = 0x100;
    memset(g_text_buf, 0, sizeof(g_text_buf));
    memset(g_text_len, 0, sizeof(g_text_len));
    ta_glass_reset();
}

const ta_draw_stats_t *ta_draw_stats(void) {
    return &g_stats;
}

void ta_draw_bind_queue(ta_queue_t *q) {
    g_q = q;
}

static void maybe_reply(const char *reply_to, ta_session_id_t session,
                        ta_event_type_t done_type) {
    ta_event_envelope_t reply;

    if (reply_to == NULL || reply_to[0] == '\0') {
        return;
    }
    ta_env_clear(&reply);
    reply.event.type = done_type;
    reply.session_id = session;
    (void)ta_env_set_src(&reply, TA_DRAW_NAME);
    if (ta_registry_post(reply_to, &reply) == 0) {
        g_stats.replies_posted++;
    }
}

static int handle_touch(uint16_t x, uint16_t y) {
    g_stats.touch++;
    g_stats.handled++;
    (void)ta_glass_touch(x, y, g_session++);
    return 0;
}

static int handle_rotate(int8_t steps) {
    g_stats.rotate++;
    g_stats.handled++;
    (void)ta_glass_rotate(steps, g_session++);
    return 0;
}

static int handle_update(const ta_event_envelope_t *env) {
    const ta_draw_update_t *u = &env->event.u.draw_update;

    g_stats.update++;
    g_stats.handled++;
    if (u->kind == TA_DRAW_UPD_CADENCE) {
        (void)ta_glass_update();
    } else if (u->kind == TA_DRAW_UPD_STATUS) {
        ta_glass_set_status(u->polled, u->desired, u->playing,
                            u->playing_polled);
    } else if (u->kind == TA_DRAW_UPD_BASE_DIRTY) {
        ta_glass_base_dirty();
    }
    /* PLAN: draw may run right after update in one actor turn. */
    (void)ta_glass_paint();
    maybe_reply(u->reply_to, env->session_id, TA_EV_DRAW_UPDATE_DONE);
    return 0;
}

static int handle_set_text(const ta_event_envelope_t *env) {
    const ta_draw_set_text_t *t = &env->event.u.draw_set_text;
    size_t n;
    size_t room;

    g_stats.set_text++;
    g_stats.handled++;
    if (t->field >= TA_DRAW_TEXT_N) {
        return -1;
    }
    if (t->flags & TA_DRAW_TEXT_FIRST) {
        g_text_len[t->field] = 0;
    }
    n = (size_t)t->n;
    if (n > TA_DRAW_TEXT_CHUNK_MAX) {
        n = TA_DRAW_TEXT_CHUNK_MAX;
    }
    room = TA_GLASS_TEXT_MAX - g_text_len[t->field];
    if (n > room) {
        n = room;
    }
    memcpy(g_text_buf[t->field] + g_text_len[t->field], t->ascii, n);
    g_text_len[t->field] += n;
    g_text_buf[t->field][g_text_len[t->field]] = '\0';
    if (t->flags & TA_DRAW_TEXT_LAST) {
        (void)ta_glass_set_text(t->field, g_text_buf[t->field]);
        (void)ta_glass_paint();
    }
    return 0;
}

int ta_draw_handle(const ta_event_envelope_t *env) {
    if (env == NULL) {
        return -1;
    }
    switch (env->event.type) {
    case TA_EV_DRAW_UPDATE:
        return handle_update(env);
    case TA_EV_DRAW_PAINT:
        g_stats.paint++;
        g_stats.handled++;
        (void)ta_glass_paint();
        maybe_reply(env->event.u.draw_paint.reply_to, env->session_id,
                    TA_EV_DRAW_PAINT_DONE);
        return 0;
    case TA_EV_ISR_TOUCH:
        return handle_touch(env->event.u.isr_touch.x, env->event.u.isr_touch.y);
    case TA_EV_DRAW_REACT_TOUCH:
        return handle_touch(env->event.u.draw_react_touch.x,
                            env->event.u.draw_react_touch.y);
    case TA_EV_ISR_ROTARY:
        return handle_rotate(env->event.u.isr_rotary.steps);
    case TA_EV_DRAW_REACT_ROTATE:
        return handle_rotate(env->event.u.draw_react_rotate.steps);
    case TA_EV_DRAW_SET_SHAPE_STACK:
        g_stats.set_stack++;
        g_stats.handled++;
        if (ta_glass_install_stack() == 0) {
            (void)ta_glass_paint();
        }
        return 0;
    case TA_EV_DRAW_LOG:
        g_stats.log++;
        g_stats.handled++;
        return 0;
    case TA_EV_DRAW_SCROLL_OX:
        g_stats.scroll++;
        g_stats.handled++;
        if (env->event.u.draw_scroll_ox.has_ox) {
            if (ta_glass_scroll_ox(env->event.u.draw_scroll_ox.ox) > 0) {
                (void)ta_glass_paint();
            }
        } else if (ta_glass_scroll_step() > 0) {
            /* Scheduler cadence: Draw owns the position. */
            (void)ta_glass_paint();
        }
        return 0;
    case TA_EV_DRAW_SET_TEXT:
        return handle_set_text(env);
    case TA_EV_DEBUG_STATUS:
        g_stats.handled++;
        return ta_debug_status_reply(env, TA_DRAW_NAME, "ok");
    case TA_EV_LIST_EVENTS:
        g_stats.handled++;
        return ta_list_events_offer(
            env, "list_events,debug_status,drawupdate,drawpaint");
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_draw_enqueue(const ta_event_envelope_t *env) {
    /* Sync replies for Controller TIMEOUT_SHORT / HTTP list_events. */
    if (env != NULL && (env->event.type == TA_EV_DEBUG_STATUS ||
                       env->event.type == TA_EV_LIST_EVENTS)) {
        return ta_draw_handle(env);
    }
    if (g_q != NULL) {
        return ta_queue_push(g_q, env);
    }
    return ta_draw_handle(env);
}

void ta_draw_start(void) {
    (void)ta_registry_register(TA_DRAW_NAME, ta_draw_enqueue);
}

/* Unbound: consume a mail directly (host convenience). */
static size_t drain_mail_direct(ta_isr_mail_t *m) {
    size_t n = 0;
    uint32_t head = m->head;
    uint32_t tail = __atomic_load_n(&m->tail, __ATOMIC_ACQUIRE);

    while (head != tail) {
        (void)ta_draw_handle(&m->slots[head]);
        head = (head + 1u) % TA_ISR_MAIL_CAP;
        n++;
        __atomic_store_n(&m->head, head, __ATOMIC_RELEASE);
        tail = __atomic_load_n(&m->tail, __ATOMIC_ACQUIRE);
    }
    return n;
}

size_t ta_draw_pump(ta_isr_mail_t *const *mails, size_t n_mails) {
    size_t handled = 0;
    size_t i;
    ta_event_envelope_t env;

    for (i = 0; i < n_mails; i++) {
        ta_isr_mail_t *m = mails[i];

        if (m == NULL) {
            continue;
        }
        if (m->drops != g_stats.isr_drops) {
            g_stats.isr_drops = m->drops;
        }
        if (g_q != NULL) {
            g_stats.isr_drained += (unsigned)ta_isr_mail_drain_to_queue(m, g_q);
        } else {
            size_t n = drain_mail_direct(m);
            g_stats.isr_drained += (unsigned)n;
            handled += n;
        }
    }
    if (g_q == NULL) {
        return handled;
    }
    while (ta_queue_try_peek(g_q, &env) == 0) {
        (void)ta_draw_handle(&env);
        ta_queue_pop(g_q);
        handled++;
    }
    return handled;
}

int ta_draw_post_text(uint8_t field, const char *ascii, ta_session_id_t session,
                      const char *src) {
    size_t len;
    size_t off = 0;

    if (ascii == NULL) {
        ascii = "";
    }
    len = strlen(ascii);
    if (len > TA_GLASS_TEXT_MAX) {
        len = TA_GLASS_TEXT_MAX;
    }
    do {
        ta_event_envelope_t env;
        size_t n = len - off;
        uint8_t flags = 0;

        if (n > TA_DRAW_TEXT_CHUNK) {
            n = TA_DRAW_TEXT_CHUNK;
        }
        if (off == 0) {
            flags |= TA_DRAW_TEXT_FIRST;
        }
        if (off + n >= len) {
            flags |= TA_DRAW_TEXT_LAST;
        }
        ta_env_clear(&env);
        env.event.type = TA_EV_DRAW_SET_TEXT;
        env.session_id = session;
        (void)ta_env_set_src(&env, src != NULL ? src : "Net");
        env.event.u.draw_set_text.field = field;
        env.event.u.draw_set_text.flags = flags;
        env.event.u.draw_set_text.n = (uint8_t)n;
        memcpy(env.event.u.draw_set_text.ascii, ascii + off, n);
        if (ta_registry_post(TA_DRAW_NAME, &env) != 0) {
            return -1;
        }
        off += n;
    } while (off < len);
    return 0;
}

int ta_draw_post_status(uint8_t polled, uint8_t desired, uint8_t playing,
                        uint8_t playing_polled, ta_session_id_t session,
                        const char *src) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.event.type = TA_EV_DRAW_UPDATE;
    env.session_id = session;
    (void)ta_env_set_src(&env, src != NULL ? src : "MPDController");
    env.event.u.draw_update.kind = (uint8_t)TA_DRAW_UPD_STATUS;
    env.event.u.draw_update.polled = polled;
    env.event.u.draw_update.desired = desired;
    env.event.u.draw_update.playing = playing;
    env.event.u.draw_update.playing_polled = playing_polled;
    return ta_registry_post(TA_DRAW_NAME, &env);
}
