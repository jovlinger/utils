/* KvConfig TaskActor: owns the linked-list KV image (get/set/list/delete). */
#ifndef SPINME_TA_KV_ACTOR_H
#define SPINME_TA_KV_ACTOR_H

#include "ta_event.h"
#include "ta_kv.h"

#include <stddef.h>

#define TA_KVCONFIG_NAME "KvConfig"

void ta_kvconfig_reset(void);
int ta_kvconfig_enqueue(const ta_event_envelope_t *env);
void ta_kvconfig_start(void);

/* Compatibility wrappers used by Log / tests (blob put + AllInformResult get). */
int ta_kv_actor_set(const char *key, const void *src, size_t n);
int ta_kv_actor_get(const char *reply_to, const char *key);

#endif
