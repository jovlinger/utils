/* Async TaskActor events: envelope header + typed body (spinme PLAN). */
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

typedef struct {
    uint8_t unused;
} ta_all_perform_init_t;

typedef struct {
    uint8_t status;
    char key[TA_ALL_KEY_MAX];
    uint16_t n;
    uint8_t bytes[TA_ALL_INFORM_MAX];
} ta_all_inform_result_t;

/* ---- per-message bodies: ta_<recipient>_<verb>_<noun>_t ---- */

typedef struct {
    char target[TA_NAME_MAX];
} ta_ctrl_set_route_t;

typedef struct {
    uint8_t severity;
    uint8_t tag;
    char text[TA_LOG_TEXT_MAX + 1];
} ta_log_emit_line_t;

typedef struct {
    uint16_t x;
    uint16_t y;
} ta_isr_touch_t;

typedef struct {
    int8_t steps;
    uint8_t vel_q8;
} ta_isr_rotary_t;

/* Net poll: response type implied (TA_EV_NET_POLL_DONE / coord inform). */
typedef struct {
    char reply_to[TA_NAME_MAX];
} ta_net_poll_playerstate_t;

typedef struct {
    char reply_to[TA_NAME_MAX];
    uint8_t op; /* TA_NET_SET_OP_* */
    ta_volume_t volume;
} ta_net_set_t;

typedef struct {
    char reply_to[TA_NAME_MAX];
    char path[TA_PATH_MAX];
} ta_net_fetch_albumart_t;

/* Coordinator (MPDController) inform from Net poll completion. */
typedef struct {
    char artist[TA_TEXT_MAX];
    char album[TA_TEXT_MAX];
    char song[TA_TEXT_MAX];
    ta_playing_state_t playing;
    ta_volume_t volume;
    int track_total_length_secs;
    int track_current_pos_secs;
} ta_coord_inform_playerstate_t;

typedef struct {
    char artist[TA_TEXT_MAX];
    char album[TA_TEXT_MAX];
    char song[TA_TEXT_MAX];
} ta_draw_inform_songinfo_t;

typedef struct {
    ta_volume_t volume;
    int actual; /* 0 = desired/target; 1 = settled from player */
} ta_draw_inform_volume_t;

typedef struct {
    int track_current_pos_secs;
} ta_draw_inform_currpos_t;

/* DRAW_UPDATE: kind selects cadence / status / base-dirty. */
enum {
    TA_DRAW_UPD_CADENCE = 0,
    TA_DRAW_UPD_STATUS = 1,
    TA_DRAW_UPD_BASE_DIRTY = 2
};

typedef struct {
    char reply_to[TA_NAME_MAX];
    uint8_t kind;
    uint8_t polled;         /* volume from player; 0xFF = keep */
    uint8_t desired;        /* volume target; 0xFF = keep */
    uint8_t playing;        /* desired play/pause 0/1; 0xFF = keep */
    uint8_t playing_polled; /* player play/pause 0/1; 0xFF = keep */
} ta_draw_update_t;

typedef struct {
    char reply_to[TA_NAME_MAX];
} ta_draw_paint_t;

typedef struct {
    uint16_t x;
    uint16_t y;
} ta_draw_react_touch_t;

typedef struct {
    int8_t steps;
} ta_draw_react_rotate_t;

typedef struct {
    int16_t ox;
    uint8_t has_ox; /* 0 = cadence step; 1 = absolute ox */
} ta_draw_scroll_ox_t;

typedef struct {
    uint8_t field;
    uint8_t flags;
    uint8_t n;
    char ascii[TA_DRAW_TEXT_CHUNK_MAX];
} ta_draw_set_text_t;

/* ControlEvents: reply_to empty => fire-and-forget; echo type implied. */
typedef struct {
    char reply_to[TA_NAME_MAX];
} ta_ctrl_toggle_t;

typedef struct {
    char reply_to[TA_NAME_MAX];
} ta_ctrl_set_active_t;

enum {
    TA_CTRL_VOL_NONE = 0, /* touch / no change */
    TA_CTRL_VOL_REL = 1,
    TA_CTRL_VOL_ABS = 2
};

typedef struct {
    char reply_to[TA_NAME_MAX];
    uint8_t mode; /* TA_CTRL_VOL_* */
    int8_t delta;
    ta_volume_t absolute;
} ta_ctrl_volume_t;

typedef struct {
    char fire_to[TA_NAME_MAX];
    ta_event_type_t fire_type;
    uint32_t period_ms;
    uint8_t flags;
} ta_sched_start_t;

typedef struct {
    uint32_t advance_ms;
} ta_sched_tick_t;

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
