/* Log accept path: sample into a bounded buffer, reject when full. */
#ifndef SPINME_TA_LOG_ACCEPT_H
#define SPINME_TA_LOG_ACCEPT_H

#include <stddef.h>
#include <stdint.h>

#define TA_LOG_ACCEPT_CAP 8
#define TA_LOG_MSG_MAX 64

typedef struct ta_log_accept_event {
    uint32_t emit_time_ms;
    char message[TA_LOG_MSG_MAX];
} ta_log_accept_event_t;

void ta_log_accept_reset(void);
/* 0 accepted, -1 rejected (full, empty, or too long). */
int ta_log_accept(uint32_t emit_time_ms, const char *message);
size_t ta_log_accept_count(void);
const ta_log_accept_event_t *ta_log_accept_at(size_t index);
unsigned ta_log_accept_rejected(void);

#endif
