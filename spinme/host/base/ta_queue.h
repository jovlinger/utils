/* Multi-producer single-consumer event queue (pthread host / FreeRTOS device). */
#ifndef SPINME_TA_QUEUE_H
#define SPINME_TA_QUEUE_H

#include "ta_event.h"
#include "ta_sync.h"

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ta_queue {
    ta_event_envelope_t *slots;
    size_t capacity;
    size_t head;
    size_t tail;
    size_t count;
    ta_mutex_t mu;
    ta_cond_t not_empty;
    unsigned drops;
} ta_queue_t;

/* Separate lock type for shape/pixel protocol (not the queue mutex). */
typedef struct ta_shape_lock {
    ta_mutex_t mu;
} ta_shape_lock_t;

int ta_queue_init(ta_queue_t *q, ta_event_envelope_t *storage, size_t capacity);
void ta_queue_fini(ta_queue_t *q);

/*
 * Producer: copies *env, stamps enqueue_time_ms = ta_now_ms().
 * Returns 0, or -1 if full (drops++).
 */
int ta_queue_push(ta_queue_t *q, const ta_event_envelope_t *env);

/* Consumer: wait until non-empty, copy head into *out without popping. */
void ta_queue_peek_wait(ta_queue_t *q, ta_event_envelope_t *out);

/* Consumer: copy head without wait; returns 0 or -1 if empty. */
int ta_queue_try_peek(ta_queue_t *q, ta_event_envelope_t *out);

/* Consumer: drop head after handle. */
void ta_queue_pop(ta_queue_t *q);

/*
 * Verb filter: return non-zero to match. Used while degraded to accept
 * informs/setup only. Walk is oldest-first among pending slots.
 */
typedef int (*ta_queue_verb_match_fn)(const ta_event_envelope_t *env, void *ctx);

/* Copy first matching pending envelope; do not pop. -1 if none. */
int ta_queue_try_peek_verb(ta_queue_t *q, ta_event_envelope_t *out,
                           ta_queue_verb_match_fn match, void *ctx);

/*
 * Selective take: swap pending slot `rel` (0=head) with head, copy it out,
 * then pop. Returns 0 or -1 if rel out of range.
 */
int ta_queue_take_at(ta_queue_t *q, size_t rel, ta_event_envelope_t *out);

/* peek_verb + take_at of the match. -1 if no match. */
int ta_queue_try_take_verb(ta_queue_t *q, ta_event_envelope_t *out,
                           ta_queue_verb_match_fn match, void *ctx);

int ta_shape_lock_init(ta_shape_lock_t *L);
void ta_shape_lock_fini(ta_shape_lock_t *L);
void ta_shape_lock_acquire(ta_shape_lock_t *L);
void ta_shape_lock_release(ta_shape_lock_t *L);

#ifdef __cplusplus
}
#endif
#endif
