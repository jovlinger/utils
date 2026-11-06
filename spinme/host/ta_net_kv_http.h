/* Net HTTP REST: PUT /kv/<key> sets one KV blob. */
#ifndef SPINME_TA_NET_KV_HTTP_H
#define SPINME_TA_NET_KV_HTTP_H

#include "ta_kv.h"

#include <stddef.h>
#include <stdint.h>

/* Parse one PUT request and ta_kv_put the body. Returns a ta_kv_status_t. */
ta_kv_status_t ta_net_kv_http_set(const uint8_t *req, size_t len);

#endif
