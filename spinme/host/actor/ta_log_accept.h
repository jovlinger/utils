/* Log accept path: sample into a bounded buffer, dump on full or cadence. */
#ifndef SPINME_TA_LOG_ACCEPT_H
#define SPINME_TA_LOG_ACCEPT_H

#include "ta_event.h"

#include <stddef.h>
#include <stdint.h>

#define TA_LOG_MSG_MAX 64
#define TA_LOG_ACCEPT_BYTES_MAX (128u * 1024u)
#define TA_LOG_ACCEPT_DEFAULT_CAP 8u
#define TA_LOG_BUFFER_KB_DEFAULT 1u
#define TA_LOG_BUFFER_KB_MAX 128u
#define TA_LOG_CADENCE_S_DEFAULT 300u

typedef struct ta_log_accept_event {
    uint32_t emit_time_ms;
    char message[TA_LOG_MSG_MAX];
} ta_log_accept_event_t;

#define TA_LOG_ACCEPT_MAX_EVENTS                                               \
    (TA_LOG_ACCEPT_BYTES_MAX / sizeof(ta_log_accept_event_t))

/* Compat aliases used by older tests. */
#define TA_LOG_ACCEPT_CAP TA_LOG_ACCEPT_DEFAULT_CAP
#define TA_LOG_EMPTY_DUE_MS ((TA_LOG_CADENCE_S_DEFAULT * 1000u) - 30000u)

void ta_log_accept_reset(void);
void ta_log_set_buffer_kb(uint16_t kb);
size_t ta_log_buffer_cap(void);
void ta_log_set_cadence_s(uint32_t seconds);
uint32_t ta_log_cadence_s(void);

int ta_log_accept(uint32_t emit_time_ms, const char *message);
/* Same as ta_log_accept but routes by ESP-IDF-style severity into rings. */
int ta_log_accept_level(uint8_t level, uint32_t emit_time_ms,
                        const char *message);
size_t ta_log_accept_count(void);
const ta_log_accept_event_t *ta_log_accept_at(size_t index);
unsigned ta_log_accept_rejected(void);

typedef int (*ta_log_send_fn)(const char *url, const ta_log_accept_event_t *rows,
                             size_t n, void *ud);

void ta_log_set_sender(ta_log_send_fn fn, void *ud);
void ta_log_set_url(const char *url);
const char *ta_log_url(void);

int ta_log_dump(uint32_t now_ms);
int ta_log_on_empty_tick(uint32_t now_ms);
uint32_t ta_log_last_empty_ms(void);

void ta_log_apply_kv_settings(void);
int ta_log_handle_envelope(const ta_event_envelope_t *env);

size_t ta_log_format_syslog(char *dst, size_t cap, uint32_t emit_time_ms,
                            const char *message);

#endif
