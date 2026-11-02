#include "ta_queue.h"

#include <stdio.h>
#include <string.h>

int ta_queue_init(ta_queue_t *q, ta_event_envelope_t *storage, size_t capacity) {
    if (q == NULL || storage == NULL || capacity < 2) {
        return -1;
    }
    memset(q, 0, sizeof(*q));
    q->slots = storage;
    q->capacity = capacity;
    if (ta_mutex_init(&q->mu) != 0) {
        return -1;
    }
    if (ta_cond_init(&q->not_empty) != 0) {
        ta_mutex_destroy(&q->mu);
        return -1;
    }
    return 0;
}

void ta_queue_fini(ta_queue_t *q) {
    if (q == NULL) {
        return;
    }
    ta_cond_destroy(&q->not_empty);
    ta_mutex_destroy(&q->mu);
}

int ta_queue_push(ta_queue_t *q, const ta_event_envelope_t *env) {
    ta_event_envelope_t slot;

    if (q == NULL || env == NULL) {
        return -1;
    }
    slot = *env;
    slot.enqueue_time_ms = ta_now_ms();
    ta_mutex_lock(&q->mu);
    if (q->count >= q->capacity) {
        q->drops++;
        fprintf(stderr, "ERROR: event queue full\n");
        ta_mutex_unlock(&q->mu);
        return -1;
    }
    q->slots[q->tail] = slot;
    q->tail = (q->tail + 1) % q->capacity;
    q->count++;
    ta_cond_signal(&q->not_empty);
    ta_mutex_unlock(&q->mu);
    return 0;
}

void ta_queue_peek_wait(ta_queue_t *q, ta_event_envelope_t *out) {
    ta_mutex_lock(&q->mu);
    while (q->count == 0) {
        ta_cond_wait(&q->not_empty, &q->mu);
    }
    *out = q->slots[q->head];
    ta_mutex_unlock(&q->mu);
}

int ta_queue_try_peek(ta_queue_t *q, ta_event_envelope_t *out) {
    int rc = -1;

    if (q == NULL || out == NULL) {
        return -1;
    }
    ta_mutex_lock(&q->mu);
    if (q->count > 0) {
        *out = q->slots[q->head];
        rc = 0;
    }
    ta_mutex_unlock(&q->mu);
    return rc;
}

void ta_queue_pop(ta_queue_t *q) {
    ta_mutex_lock(&q->mu);
    if (q->count > 0) {
        q->head = (q->head + 1) % q->capacity;
        q->count--;
    }
    ta_mutex_unlock(&q->mu);
}

int ta_shape_lock_init(ta_shape_lock_t *L) {
    if (L == NULL) {
        return -1;
    }
    return ta_mutex_init(&L->mu);
}

void ta_shape_lock_fini(ta_shape_lock_t *L) {
    if (L != NULL) {
        ta_mutex_destroy(&L->mu);
    }
}

void ta_shape_lock_acquire(ta_shape_lock_t *L) {
    if (L != NULL) {
        ta_mutex_lock(&L->mu);
    }
}

void ta_shape_lock_release(ta_shape_lock_t *L) {
    if (L != NULL) {
        ta_mutex_unlock(&L->mu);
    }
}
