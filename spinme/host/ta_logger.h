/* Logger TaskActor: aggregate log events; policy NVM / external / drop. */
#ifndef SPINME_TA_LOGGER_H
#define SPINME_TA_LOGGER_H

#include "ta_event.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif


#define TA_LOGGER_NAME "Logger"

typedef enum {
    TA_LOG_POLICY_DROP = 0,
    TA_LOG_POLICY_NVM = 1,
    TA_LOG_POLICY_EXTERNAL = 2
} ta_log_policy_t;

/* Payload layout for TA_EV_LOG: [severity u8][tag u8][text...] */
typedef struct ta_log_stats {
    unsigned accepted;
    unsigned dropped;
    unsigned nvm;
    unsigned external;
} ta_log_stats_t;

void ta_logger_reset(void);
void ta_logger_start(void); /* register name + queue; call from Init entry */
int ta_logger_enqueue(const ta_event_t *ev);
void ta_logger_set_policy(uint8_t severity, ta_log_policy_t policy);
ta_log_policy_t ta_logger_policy(uint8_t severity);
/* Drain up to max events; returns number handled. */
size_t ta_logger_drain(size_t max);
const ta_log_stats_t *ta_logger_stats(void);

/* Helper: build and post TA_EV_LOG via registry (or direct enqueue). */
int ta_logger_emit(ta_session_id_t session, const char *src, uint8_t severity,
                   uint8_t tag, const char *text);


#ifdef __cplusplus
}
#endif
#endif
