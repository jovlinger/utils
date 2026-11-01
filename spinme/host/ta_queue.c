#include "ta_queue.h"

#include <stdio.h>
#include <string.h>

int ta_queue_init(ta_queue_t *q, ta_event_t *storage, size_t capacity) {
    if (q == NULL || storage == NULL || capacity < 2) {
        return -1;
    }
    memset(q, 0, sizeof(*q));
    q->slots = storage;
    q->capacity = capacity;
    if (pthread_mutex_init(&q->mu, NULL) != 0) {
        return -1;
    }
    if (pthread_cond_init(&q->not_empty, NULL) != 0) {
        pthread_mutex_destroy(&q->mu);
        return -1;
    }
    return 0;
}

void ta_queue_fini(ta_queue_t *q) {
    if (q == NULL) {
        return;
    }
    pthread_cond_destroy(&q->not_empty);
    pthread_mutex_destroy(&q->mu);
}

int ta_queue_push(ta_queue_t *q, const ta_event_t *ev) {
    if (q == NULL || ev == NULL) {
        return -1;
    }
    pthread_mutex_lock(&q->mu);
    if (q->count >= q->capacity) {
        q->drops++;
        fprintf(stderr, "ERROR: event queue full\n");
        pthread_mutex_unlock(&q->mu);
        return -1;
    }
    q->slots[q->tail] = *ev;
    q->tail = (q->tail + 1) % q->capacity;
    q->count++;
    pthread_cond_signal(&q->not_empty);
    pthread_mutex_unlock(&q->mu);
    return 0;
}

void ta_queue_peek_wait(ta_queue_t *q, ta_event_t *out) {
    pthread_mutex_lock(&q->mu);
    while (q->count == 0) {
        pthread_cond_wait(&q->not_empty, &q->mu);
    }
    *out = q->slots[q->head];
    pthread_mutex_unlock(&q->mu);
}

void ta_queue_pop(ta_queue_t *q) {
    pthread_mutex_lock(&q->mu);
    if (q->count > 0) {
        q->head = (q->head + 1) % q->capacity;
        q->count--;
    }
    pthread_mutex_unlock(&q->mu);
}

int ta_shape_lock_init(ta_shape_lock_t *L) {
    if (L == NULL) {
        return -1;
    }
    return pthread_mutex_init(&L->mu, NULL) == 0 ? 0 : -1;
}

void ta_shape_lock_fini(ta_shape_lock_t *L) {
    if (L != NULL) {
        pthread_mutex_destroy(&L->mu);
    }
}

void ta_shape_lock_acquire(ta_shape_lock_t *L) {
    pthread_mutex_lock(&L->mu);
}

void ta_shape_lock_release(ta_shape_lock_t *L) {
    pthread_mutex_unlock(&L->mu);
}
