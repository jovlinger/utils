/* Three-ring circular log store (ERROR / WARN / INFO-and-below). */
#ifndef SPINME_TA_LOG_RINGS_H
#define SPINME_TA_LOG_RINGS_H

#include <stddef.h>
#include <stdint.h>

/* Host keeps one malloc arena. A later device WI can map the same
 * offset-based layout in PSRAM: define TA_LOG_RINGS_PSRAM and provide
 * ta_log_rings_psram_alloc / ta_log_rings_psram_free (malloc/free
 * contract). Nothing here calls those until the arena is (re)built. */
#ifdef TA_LOG_RINGS_PSRAM
void *ta_log_rings_psram_alloc(size_t bytes);
void ta_log_rings_psram_free(void *ptr);
#endif

#define TA_LOG_RINGS_ERROR_CAP (128u * 1024u)
#define TA_LOG_RINGS_WARN_CAP (128u * 1024u)
#define TA_LOG_RINGS_INFO_CAP (256u * 1024u)
#define TA_LOG_RINGS_TOTAL_CAP                                                 \
    (TA_LOG_RINGS_ERROR_CAP + TA_LOG_RINGS_WARN_CAP + TA_LOG_RINGS_INFO_CAP)
#define TA_LOG_RINGS_TEXT_MAX 1024u
#define TA_LOG_RINGS_OVERRUN_TEXT "log overrun"

/* Numeric values match the ESP-IDF severity scale so Log accept can pass
 * ta_log_emit_line_t.severity through unchanged. ERROR and WARN have
 * their own rings. INFO, DEBUG, VERBOSE, and any other value share the
 * INFO-and-below ring. The node still stores the original level. */
typedef enum ta_log_level {
    TA_LOG_LEVEL_NONE = 0,
    TA_LOG_LEVEL_ERROR = 1,
    TA_LOG_LEVEL_WARN = 2,
    TA_LOG_LEVEL_INFO = 3,
    TA_LOG_LEVEL_DEBUG = 4,
    TA_LOG_LEVEL_VERBOSE = 5
} ta_log_level_t;

typedef enum ta_log_ring_id {
    TA_LOG_RING_ERROR = 0,
    TA_LOG_RING_WARN = 1,
    TA_LOG_RING_INFO = 2,
    TA_LOG_RING_COUNT = 3
} ta_log_ring_id_t;

/* text points into the arena. It is invalid after the next insert,
 * set_caps, or reset. */
typedef struct ta_log_rings_entry {
    uint8_t level;
    uint8_t ring;
    uint32_t repeat;
    uint32_t seq;
    uint64_t time_ms;
    const char *text;
} ta_log_rings_entry_t;

/* Snapshot in (time_ms, seq) order. Zero the struct before begin.
 * Call end before begin again. Insert/set_caps/reset invalidate it. */
typedef struct ta_log_rings_iter {
    uint32_t *offs;
    uint32_t n;
    uint32_t i;
} ta_log_rings_iter_t;

/* Caps are byte budgets, rounded up to a multiple of 8. Replaces the
 * arena and drops every stored line. Returns 0, or -1 if the sizes
 * overflow or the arena cannot be allocated (previous store kept). */
int ta_log_rings_set_caps(uint32_t error_bytes, uint32_t warn_bytes,
                          uint32_t info_bytes);

/* Default caps (128 + 128 + 256 KiB) and an empty store. */
int ta_log_rings_reset(void);

uint32_t ta_log_rings_cap(ta_log_ring_id_t ring);
uint32_t ta_log_rings_count(ta_log_ring_id_t ring);

/* Aligned bytes one node needs for a message of text_len (no NUL).
 * Returns 0 when text_len is above TA_LOG_RINGS_TEXT_MAX. */
uint32_t ta_log_rings_node_bytes(size_t text_len);

/* Append to the ring selected by level. Identical text on that ring's
 * tail bumps repeat and refreshes time_ms instead of allocating.
 * When the ring cannot fit a new node, a WARN "log overrun" is written
 * to the WARN ring, the oldest node on the overflowing ring is dropped,
 * and the insert is retried. Returns 0, or -1 if text is NULL/empty/too
 * long or larger than that ring's cap. */
int ta_log_rings_insert(uint8_t level, uint64_t time_ms, const char *text);

/* index 0 is the oldest line on that ring. Returns 0, or -1. */
int ta_log_rings_at(ta_log_ring_id_t ring, uint32_t index,
                    ta_log_rings_entry_t *out);

int ta_log_rings_iter_begin(ta_log_rings_iter_t *it);
/* Returns 1 and fills *out, or 0 when the snapshot is exhausted. */
int ta_log_rings_iter_next(ta_log_rings_iter_t *it, ta_log_rings_entry_t *out);
void ta_log_rings_iter_end(ta_log_rings_iter_t *it);

/* Drop every node with seq <= through_seq from all rings (ACK cursor).
 * Returns the number of nodes dropped. */
uint32_t ta_log_rings_ack_through(uint32_t through_seq);

#endif
