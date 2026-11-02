/* NVM KV: string key -> length-known bytes; copy-out Get (Config-owned). */
#ifndef SPINME_TA_KV_H
#define SPINME_TA_KV_H

#include <stddef.h>
#include <stdint.h>

#define TA_KV_KEY_MAX 32
#define TA_KV_VAL_MAX 256
#define TA_KV_SLOTS 32

#define TA_KV_KEY_CONTROLLER "current_controller"

typedef enum {
    TA_KV_OK = 0,
    TA_KV_MISSING = 1,
    TA_KV_TOO_SMALL = 2,
    TA_KV_BAD_ARG = 3,
    TA_KV_FULL = 4
} ta_kv_status_t;

void ta_kv_reset(void);
int ta_kv_has(const char *key); /* 1 or 0 */
/* On OK writes *out_len; MISSING if absent. */
ta_kv_status_t ta_kv_get_len(const char *key, size_t *out_len);
/* Copy into dst; TOO_SMALL sets *out_len to needed size. */
ta_kv_status_t ta_kv_get(const char *key, void *dst, size_t dst_cap,
                         size_t *out_len);
ta_kv_status_t ta_kv_put(const char *key, const void *src, size_t len);
ta_kv_status_t ta_kv_delete(const char *key);

/* Config facade helpers. */
ta_kv_status_t ta_config_get_controller(char *dst, size_t dst_cap,
                                        size_t *out_len);
ta_kv_status_t ta_config_put_controller(const char *name);

#endif
