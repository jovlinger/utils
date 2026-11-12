/* Net HTTP REST: PUT /kv/<key> writes one KV blob (code or config).
 * Named put so later verbs (GET/DELETE) can share this module. */
#ifndef SPINME_TA_NET_KV_HTTP_H
#define SPINME_TA_NET_KV_HTTP_H

#include "ta_kv.h"

#include <stddef.h>
#include <stdint.h>

/* Parse one PUT /kv/<key> request and ta_kv_put the body. */
ta_kv_status_t ta_net_kv_http_put(const uint8_t *req, size_t len);

#endif
