/* Actor face on the dead-simple KV image. Get replies with ta_all_inform_result. */
#ifndef SPINME_TA_KV_ACTOR_H
#define SPINME_TA_KV_ACTOR_H

#include "ta_kv.h"

#include <stddef.h>

/* Store a value. Returns 0 on TA_KV_OK, -1 otherwise. */
int ta_kv_actor_set(const char *key, const void *src, size_t n);
/* Read key and post TA_EV_ALL_INFORM_RESULT to reply_to. 0 if the post landed. */
int ta_kv_actor_get(const char *reply_to, const char *key);

#endif
