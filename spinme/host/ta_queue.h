/* Multi-producer single-consumer event queue (host pthread stand-in). */
#ifndef SPINME_TA_QUEUE_H
#define SPINME_TA_QUEUE_H

#include "ta_event.h"

#include <pthread.h>
#include <stddef.h>

typedef struct ta_queue {
    ta_event_t *slots;
    size_t capacity;
    size_t head;
    size_t tail;
    size_t count;
    pthread_mutex_t mu;
    pthread_cond_t not_empty;
    unsigned drops;
} ta_queue_t;

/* Separate lock type for shape/pixel protocol (not the queue mutex). */
typedef struct ta_shape_lock {
    pthread_mutex_t mu;
} ta_shape_lock_t;

int ta_queue_init(ta_queue_t *q, ta_event_t *storage, size_t capacity);
void ta_queue_fini(ta_queue_t *q);

/* Producer: mutex only for push metadata. Returns 0, or -1 if full (drops++). */
int ta_queue_push(ta_queue_t *q, const ta_event_t *ev);

/* Consumer: wait until non-empty, copy head into *out without popping. */
void ta_queue_peek_wait(ta_queue_t *q, ta_event_t *out);

/* Consumer: copy head without wait; returns 0 or -1 if empty. */
int ta_queue_try_peek(ta_queue_t *q, ta_event_t *out);

/* Consumer: drop head after handle. */
void ta_queue_pop(ta_queue_t *q);

int ta_shape_lock_init(ta_shape_lock_t *L);
void ta_shape_lock_fini(ta_shape_lock_t *L);
void ta_shape_lock_acquire(ta_shape_lock_t *L);
void ta_shape_lock_release(ta_shape_lock_t *L);

#endif
