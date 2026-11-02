#include "ta_draw_events.h"

#include "ta_draw_glass.h"
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

static void maybe_reply(const ta_event_t *ev, ta_event_type_t done_type) {
    ta_event_t reply;

    if (ev->reply_to[0] == '\0') {
        return;
    }
    ta_event_clear(&reply);
    reply.type = done_type;
    reply.session_id = ev->session_id;
    (void)ta_event_set_src(&reply, TA_DRAW_NAME);
    if (ta_registry_post(ev->reply_to, &reply) == 0) {
        g_stats.replies_posted++;
    }
}

static uint16_t rd_u16(const uint8_t *p) {
    return (uint16_t)(p[0] | ((uint16_t)p[1] << 8));
}

static int handle_touch(const ta_event_t *ev) {
    uint16_t x;
    uint16_t y;

    g_stats.touch++;
    g_stats.handled++;
    if (ev->payload_len < 4) {
        return 0; /* legacy no-payload REACT_TOUCH: counted only */
    }
    x = rd_u16(ev->payload);
    y = rd_u16(ev->payload + 2);
    (void)ta_glass_touch(x, y, g_session++);
    return 0;
}

static int handle_rotate(const ta_event_t *ev) {
    g_stats.rotate++;
    g_stats.handled++;
    if (ev->payload_len < 1) {
        return 0;
    }
    (void)ta_glass_rotate((int8_t)ev->payload[0], g_session++);
    return 0;
}

static int handle_update(const ta_event_t *ev) {
    g_stats.update++;
    g_stats.handled++;
    if (ev->payload_len == 0) {
        (void)ta_glass_update();
    } else if (ev->payload[0] == TA_DRAW_UPD_STATUS && ev->payload_len >= 4) {
        ta_glass_set_status(ev->payload[1], ev->payload[2], ev->payload[3]);
    } else if (ev->payload[0] == TA_DRAW_UPD_BASE_DIRTY) {
        ta_glass_base_dirty();
    }
    /* PLAN: draw may run right after update in one actor turn. */
    (void)ta_glass_paint();
    maybe_reply(ev, TA_EV_DRAW_UPDATE_DONE);
    return 0;
}

static int handle_set_text(const ta_event_t *ev) {
    uint8_t field;
    uint8_t flags;
    size_t n;
    size_t room;

    g_stats.set_text++;
    g_stats.handled++;
    if (ev->payload_len < 2) {
        return -1;
    }
    field = ev->payload[0];
    flags = ev->payload[1];
    if (field >= TA_DRAW_TEXT_N) {
        return -1;
    }
    if (flags & TA_DRAW_TEXT_FIRST) {
        g_text_len[field] = 0;
    }
    n = (size_t)ev->payload_len - 2u;
    room = TA_GLASS_TEXT_MAX - g_text_len[field];
    if (n > room) {
        n = room;
    }
    memcpy(g_text_buf[field] + g_text_len[field], ev->payload + 2, n);
    g_text_len[field] += n;
    g_text_buf[field][g_text_len[field]] = '\0';
    if (flags & TA_DRAW_TEXT_LAST) {
        (void)ta_glass_set_text(field, g_text_buf[field]);
        (void)ta_glass_paint();
    }
    return 0;
}

int ta_draw_handle(const ta_event_t *ev) {
    if (ev == NULL) {
        return -1;
    }
    switch (ev->type) {
    case TA_EV_DRAW_UPDATE:
        return handle_update(ev);
    case TA_EV_DRAW_PAINT:
        g_stats.paint++;
        g_stats.handled++;
        (void)ta_glass_paint();
        maybe_reply(ev, TA_EV_DRAW_PAINT_DONE);
        return 0;
    case TA_EV_ISR_TOUCH:
    case TA_EV_DRAW_REACT_TOUCH:
        return handle_touch(ev);
    case TA_EV_ISR_ROTARY:
    case TA_EV_DRAW_REACT_ROTATE:
        return handle_rotate(ev);
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
        if (ev->payload_len >= 2) {
            int16_t ox = (int16_t)rd_u16(ev->payload);
            if (ta_glass_scroll_ox(ox) > 0) {
                (void)ta_glass_paint();
            }
        } else if (ta_glass_scroll_step() > 0) {
            /* Scheduler cadence: Draw owns the position. */
            (void)ta_glass_paint();
        }
        return 0;
    case TA_EV_DRAW_SET_TEXT:
        return handle_set_text(ev);
    default:
        g_stats.unknown++;
        return -1;
    }
}

int ta_draw_enqueue(const ta_event_t *ev) {
    if (g_q != NULL) {
        return ta_queue_push(g_q, ev);
    }
    return ta_draw_handle(ev);
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
    ta_event_t ev;

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
    while (ta_queue_try_peek(g_q, &ev) == 0) {
        (void)ta_draw_handle(&ev);
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
        ta_event_t ev;
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
        ta_event_clear(&ev);
        ev.type = TA_EV_DRAW_SET_TEXT;
        ev.session_id = session;
        (void)ta_event_set_src(&ev, src != NULL ? src : "Net");
        ev.payload[0] = field;
        ev.payload[1] = flags;
        memcpy(ev.payload + 2, ascii + off, n);
        ev.payload_len = (uint16_t)(2u + n);
        if (ta_registry_post(TA_DRAW_NAME, &ev) != 0) {
            return -1;
        }
        off += n;
    } while (off < len);
    return 0;
}

int ta_draw_post_status(uint8_t polled, uint8_t desired, uint8_t playing,
                        ta_session_id_t session, const char *src) {
    ta_event_t ev;
    uint8_t pl[4];

    ta_event_clear(&ev);
    ev.type = TA_EV_DRAW_UPDATE;
    ev.session_id = session;
    (void)ta_event_set_src(&ev, src != NULL ? src : "MPDController");
    pl[0] = (uint8_t)TA_DRAW_UPD_STATUS;
    pl[1] = polled;
    pl[2] = desired;
    pl[3] = playing;
    (void)ta_event_set_payload(&ev, pl, 4);
    return ta_registry_post(TA_DRAW_NAME, &ev);
}
