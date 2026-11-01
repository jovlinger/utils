/* Global name -> enqueueFn registry (one mutex; not held across handlers). */
#ifndef SPINME_TA_REGISTRY_H
#define SPINME_TA_REGISTRY_H

#include "ta_event.h"

typedef int (*ta_enqueue_fn)(const ta_event_t *ev);

void ta_registry_reset(void);
int ta_registry_register(const char *name, ta_enqueue_fn fn);
ta_enqueue_fn ta_registry_lookup(const char *name);
/* Lookup + call; returns -1 if missing or enqueue fails. */
int ta_registry_post(const char *name, const ta_event_t *ev);

#endif
