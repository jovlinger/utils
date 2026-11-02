/* Portable mutex / cond for host (pthread) and device (FreeRTOS). */
#ifndef SPINME_TA_SYNC_H
#define SPINME_TA_SYNC_H

#ifdef SPINME_TA_DEVICE
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"

typedef SemaphoreHandle_t ta_mutex_t;
typedef SemaphoreHandle_t ta_cond_t;

static inline int ta_mutex_init(ta_mutex_t *m) {
    if (m == NULL) {
        return -1;
    }
    *m = xSemaphoreCreateMutex();
    return *m != NULL ? 0 : -1;
}

static inline void ta_mutex_destroy(ta_mutex_t *m) {
    if (m != NULL && *m != NULL) {
        vSemaphoreDelete(*m);
        *m = NULL;
    }
}

static inline void ta_mutex_lock(ta_mutex_t *m) {
    (void)xSemaphoreTake(*m, portMAX_DELAY);
}

static inline void ta_mutex_unlock(ta_mutex_t *m) {
    (void)xSemaphoreGive(*m);
}

static inline int ta_cond_init(ta_cond_t *c) {
    if (c == NULL) {
        return -1;
    }
    /* Counting semaphore used as wake signal (binary). */
    *c = xSemaphoreCreateBinary();
    return *c != NULL ? 0 : -1;
}

static inline void ta_cond_destroy(ta_cond_t *c) {
    if (c != NULL && *c != NULL) {
        vSemaphoreDelete(*c);
        *c = NULL;
    }
}

static inline void ta_cond_signal(ta_cond_t *c) {
    (void)xSemaphoreGive(*c);
}

/* Wait while holding mutex: unlock, block on cond, re-lock. */
static inline void ta_cond_wait(ta_cond_t *c, ta_mutex_t *m) {
    ta_mutex_unlock(m);
    (void)xSemaphoreTake(*c, portMAX_DELAY);
    ta_mutex_lock(m);
}

#else /* host */

#include <pthread.h>

typedef pthread_mutex_t ta_mutex_t;
typedef pthread_cond_t ta_cond_t;

static inline int ta_mutex_init(ta_mutex_t *m) {
    return pthread_mutex_init(m, NULL) == 0 ? 0 : -1;
}

static inline void ta_mutex_destroy(ta_mutex_t *m) {
    (void)pthread_mutex_destroy(m);
}

static inline void ta_mutex_lock(ta_mutex_t *m) {
    (void)pthread_mutex_lock(m);
}

static inline void ta_mutex_unlock(ta_mutex_t *m) {
    (void)pthread_mutex_unlock(m);
}

static inline int ta_cond_init(ta_cond_t *c) {
    return pthread_cond_init(c, NULL) == 0 ? 0 : -1;
}

static inline void ta_cond_destroy(ta_cond_t *c) {
    (void)pthread_cond_destroy(c);
}

static inline void ta_cond_signal(ta_cond_t *c) {
    (void)pthread_cond_signal(c);
}

static inline void ta_cond_wait(ta_cond_t *c, ta_mutex_t *m) {
    (void)pthread_cond_wait(c, m);
}

#endif /* SPINME_TA_DEVICE */

#endif
