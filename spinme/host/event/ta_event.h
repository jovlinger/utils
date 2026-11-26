/* Async TaskActor events: envelope header + typed body.
 * Normative field layouts / codecs: spinme/taskevent (Python SoT).
 * Binary on-wire body is packed little-endian in that module's field order;
 * in-memory structs here may include ABI padding.
 */
#ifndef SPINME_TA_EVENT_H
#define SPINME_TA_EVENT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TA_NAME_MAX 24
#define TA_TEXT_MAX 96
#define TA_PATH_MAX 48
#define TA_LOG_TEXT_MAX 30
#define TA_DRAW_TEXT_CHUNK_MAX 30

typedef uint16_t ta_event_type_t;
typedef uint32_t ta_session_id_t;
typedef uint32_t ta_time_ms_t;

typedef uint8_t ta_playing_state_t;
enum {
    TA_PLAYING_STOP = 0,
    TA_PLAYING_PLAY = 1,
    TA_PLAYING_PAUSE = 2
};

typedef uint8_t ta_volume_t; /* 0..100; 0xFF = unknown where noted */

/* Built-in types reserved for foundation (actors add their own ranges). */
enum {
    TA_EV_NOP = 0,
    TA_EV_LOG = 1,
    TA_EV_SET_ROUTE = 2,
    TA_EV_ALL_PERFORM_INIT = 3,  /* startup broadcast to every registered actor */
    TA_EV_ALL_INFORM_RESULT = 4  /* universal async reply */
};

#define TA_ALL_KEY_MAX 32
#define TA_ALL_INFORM_MAX 64
#define TA_NET_HTTP_REPLY_MAX 64
#define TA_TEST_SEL_MAX 48

/* Test actor (dev / post-flash). Modes for ta_test_run_t.mode. */
/* Controller debug fan-out (HTTP: complete -> 200, TIMEOUT_SHORT miss -> 201). */
enum {
    TA_EV_DEBUG_ALL = 0x406,
    TA_EV_DEBUG_STATUS = 0x407,
    TA_EV_LIST_EVENTS = 0x408, /* every TaskActor: offer accepted event slugs */
    TA_EV_LIST_TASKS = 0x409   /* Controller: offer registered TaskActor names */
};

enum {
    TA_EV_TEST_RUN = 0x600,
    TA_EV_TEST_GET_DEBUG = 0x601,
    TA_EV_TEST_DONE = 0x610
};

/* KvConfig TaskActor (owns linked-list KV image). */
enum {
    TA_EV_KV_GET = 0x700,
    TA_EV_KV_SET = 0x701,
    TA_EV_KV_LIST = 0x702,
    TA_EV_KV_DELETE = 0x703
};
enum {
    TA_TEST_MODE_ONE = 0,
    TA_TEST_MODE_SUITE = 1,
    TA_TEST_MODE_TIMING = 2
};

/* DRAW_UPDATE: kind selects cadence / status / base-dirty. */
enum {
    TA_DRAW_UPD_CADENCE = 0,
    TA_DRAW_UPD_STATUS = 1,
    TA_DRAW_UPD_BASE_DIRTY = 2
};

enum {
    TA_CTRL_VOL_NONE = 0, /* touch / no change */
    TA_CTRL_VOL_REL = 1,
    TA_CTRL_VOL_ABS = 2
};

/* Body typedefs: generated from spinme/taskevent (Python SoT). */
#include "ta_event_bodies.gen.h"

typedef struct ta_event {
    ta_event_type_t type;
    union {
        ta_ctrl_set_route_t ctrl_set_route;
        ta_log_emit_line_t log_emit_line;
        ta_isr_touch_t isr_touch;
        ta_isr_rotary_t isr_rotary;
        ta_net_poll_playerstate_t net_poll_playerstate;
        ta_net_set_t net_set;
        ta_net_fetch_albumart_t net_fetch_albumart;
        ta_coord_inform_playerstate_t coord_inform_playerstate;
        ta_draw_inform_songinfo_t draw_inform_songinfo;
        ta_draw_inform_volume_t draw_inform_volume;
        ta_draw_inform_currpos_t draw_inform_currpos;
        ta_draw_update_t draw_update;
        ta_draw_paint_t draw_paint;
        ta_draw_react_touch_t draw_react_touch;
        ta_draw_react_rotate_t draw_react_rotate;
        ta_draw_scroll_ox_t draw_scroll_ox;
        ta_draw_set_text_t draw_set_text;
        ta_ctrl_toggle_t ctrl_toggle;
        ta_ctrl_set_active_t ctrl_set_active;
        ta_ctrl_volume_t ctrl_volume;
        ta_sched_start_t sched_start;
        ta_sched_tick_t sched_tick;
        ta_all_perform_init_t all_perform_init;
        ta_all_inform_result_t all_inform_result;
        ta_net_http_reply_t net_http_reply;
        ta_net_log_drain_t net_log_drain;
        ta_net_log_drain_ack_t net_log_drain_ack;
        ta_debug_status_t debug_status;
        ta_test_run_t test_run;
        ta_test_done_t test_done;
        ta_kv_get_t kv_get;
        ta_kv_set_t kv_set;
        ta_kv_delete_t kv_delete;
    } u;
} ta_event_t;

/* Queue slot / registry post unit. enqueue_time_ms set by queue on push. */
typedef struct ta_event_envelope {
    char src[TA_NAME_MAX];
    ta_session_id_t session_id;
    ta_time_ms_t enqueue_time_ms;
    ta_event_t event;
} ta_event_envelope_t;

void ta_event_clear(ta_event_t *ev);
void ta_env_clear(ta_event_envelope_t *env);

int ta_env_set_src(ta_event_envelope_t *env, const char *name);
int ta_copy_name(char *dst, size_t cap, const char *name);

int ta_event_set_net_poll_playerstate(ta_event_t *ev, const char *reply_to);
int ta_event_set_net_set(ta_event_t *ev, const char *reply_to, uint8_t op,
                         ta_volume_t volume);
int ta_event_set_ctrl_set_route(ta_event_t *ev, const char *target);
int ta_event_set_all_inform_result(ta_event_t *ev, uint8_t status,
                                   const char *key, const void *bytes,
                                   size_t n);

int ta_event_set_sched_start(ta_event_t *ev, const char *fire_to,
                             ta_event_type_t fire_type, uint32_t period_ms,
                             uint8_t flags);

uint32_t ta_now_ms(void);

/* Log prefix: "time|session|actor" into buf; returns bytes written excl NUL. */
size_t ta_log_prefix(char *buf, size_t cap, uint32_t time_ms,
                     ta_session_id_t session, const char *actor);

#ifdef __cplusplus
}
#endif
#endif
