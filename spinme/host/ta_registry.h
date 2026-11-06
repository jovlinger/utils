/* Global name -> enqueueFn registry (one mutex; not held across handlers). */
#ifndef SPINME_TA_REGISTRY_H
#define SPINME_TA_REGISTRY_H

#include "ta_event.h"

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef int (*ta_enqueue_fn)(const ta_event_envelope_t *env);

void ta_registry_reset(void);
int ta_registry_register(const char *name, ta_enqueue_fn fn);
/* Drop name. 0 if removed, -1 if missing or bad args. */
int ta_registry_unregister(const char *name);
ta_enqueue_fn ta_registry_lookup(const char *name);
/* Lookup + call; returns -1 if missing or enqueue fails. */
int ta_registry_post(const char *name, const ta_event_envelope_t *env);
/* Copy registered names into dst[i * stride]. Returns the count copied. */
size_t ta_registry_copy_names(char *dst, size_t stride, size_t max);

#ifdef __cplusplus
}
#endif
#endif
