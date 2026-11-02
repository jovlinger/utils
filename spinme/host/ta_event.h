/* Async TaskActor event envelope (spinme PLAN). No synchronous replies. */
#ifndef SPINME_TA_EVENT_H
#define SPINME_TA_EVENT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif


#define TA_NAME_MAX 24
#define TA_PAYLOAD_MAX 32

typedef uint16_t ta_event_type_t;
typedef uint32_t ta_session_id_t;

typedef struct ta_event {
    ta_event_type_t type;
    char src[TA_NAME_MAX];
    ta_session_id_t session_id;
    /* Optional completion callback: empty reply_to means none. */
    char reply_to[TA_NAME_MAX];
    ta_event_type_t reply_type;
    uint16_t payload_len;
    uint8_t payload[TA_PAYLOAD_MAX];
} ta_event_t;

/* Built-in types reserved for foundation (actors add their own ranges). */
enum {
    TA_EV_NOP = 0,
    TA_EV_LOG = 1,
    TA_EV_SET_ROUTE = 2
};

void ta_event_clear(ta_event_t *ev);
int ta_event_set_src(ta_event_t *ev, const char *name);
int ta_event_set_reply(ta_event_t *ev, const char *actor, ta_event_type_t type);
int ta_event_set_payload(ta_event_t *ev, const void *bytes, size_t len);

/* Log prefix: "time|session|actor" into buf; returns bytes written excl NUL. */
size_t ta_log_prefix(char *buf, size_t cap, uint32_t time_ms,
                     ta_session_id_t session, const char *actor);


#ifdef __cplusplus
}
#endif
#endif
