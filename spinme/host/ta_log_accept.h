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

/* 4 minutes 30 seconds. Scheduler asks every 5 minutes; dump only if due. */
#define TA_LOG_EMPTY_DUE_MS 270000u

typedef int (*ta_log_send_fn)(const char *url, const ta_log_accept_event_t *rows,
                             size_t n, void *ud);

void ta_log_set_sender(ta_log_send_fn fn, void *ud);
void ta_log_set_url(const char *url);
/* Send whatever is buffered, then always clear and stamp last-emptied.
 * A send error (404/502) does not keep the lines. Returns 0.
 */
int ta_log_dump(uint32_t now_ms);
/* If never dumped, or now is more than 4:30 after the last dump, dump. */
int ta_log_on_empty_tick(uint32_t now_ms);
uint32_t ta_log_last_empty_ms(void);

#endif
