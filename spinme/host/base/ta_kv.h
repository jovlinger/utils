/* Linked-list KV image owned by the KvConfig TaskActor.
 *
 * Image head: uint32 first (0 = empty). Each live item (offset >= 4):
 *   uint32 packed;  keylen:8 | vallen:20 | type:4  (low to high)
 *   uint32 next;    byte offset of next live item, or 0
 *   uint8  key[keylen];
 *   uint8  value[vallen];
 *
 * Item size is 8 + keylen + vallen (no separate entrylen). Keys stay in
 * ascending lexicographic order along the live chain. next need not be
 * adjacent (holes from unlink / first-fit reuse).
 *
 * Payload types (4-bit): see TA_KV_VTYPE_*.
 */
#ifndef SPINME_TA_KV_H
#define SPINME_TA_KV_H

#include <stddef.h>
#include <stdint.h>

#define TA_KV_KEY_MAX 32
#define TA_KV_VAL_MAX 1024
#define TA_KV_SLOTS 32

#define TA_KV_IMAGE_HEAD_SIZE 4u
/* packed u32 + next u32 (key and value follow). */
#define TA_KV_REC_PREFIX_SIZE 8u

#define TA_KV_KEY_CONTROLLER "current_controller"
#define TA_KV_KEY_LOG_URL "log_receiver_url"
#define TA_KV_KEY_LOGTARGET "logtarget"
#define TA_KV_KEY_LOG_BUFFER_KB "log_buffer_kb"
#define TA_KV_KEY_LOG_CADENCE_S "log_cadence_s"
#define TA_KV_KEY_ACTORS "actors_to_start"

/* 4-bit type discriminant in packed word. */
#define TA_KV_VTYPE_BOOL 0u
#define TA_KV_VTYPE_INT 1u
#define TA_KV_VTYPE_STR 2u
#define TA_KV_VTYPE_BLOB 3u
#define TA_KV_VTYPE_EXECUTABLE 4u
#define TA_KV_VTYPE_BITMAP 5u
/* Aliases kept for call sites that still say string/i32/smallint. */
#define TA_KV_VTYPE_STRING TA_KV_VTYPE_STR
#define TA_KV_VTYPE_INT32 TA_KV_VTYPE_INT
#define TA_KV_VTYPE_SMALLINT TA_KV_VTYPE_INT

#define TA_KV_PACK_KEYLEN(p) ((uint32_t)(p) & 0xffu)
#define TA_KV_PACK_VALLEN(p) (((uint32_t)(p) >> 8) & 0xfffffu)
#define TA_KV_PACK_TYPE(p) (((uint32_t)(p) >> 28) & 0xfu)
#define TA_KV_PACK(keylen, vallen, type)                                       \
    ((((uint32_t)(keylen) & 0xffu)) |                                          \
     ((((uint32_t)(vallen) & 0xfffffu)) << 8) |                                \
     ((((uint32_t)(type) & 0xfu)) << 28))

typedef enum {
    TA_KV_OK = 0,
    TA_KV_MISSING = 1,
    TA_KV_TOO_SMALL = 2,
    TA_KV_BAD_ARG = 3,
    TA_KV_FULL = 4,
    TA_KV_BAD_TYPE = 5
} ta_kv_status_t;

void ta_kv_reset(void);
int ta_kv_has(const char *key); /* 1 or 0 */
ta_kv_status_t ta_kv_get_len(const char *key, size_t *out_len);
ta_kv_status_t ta_kv_get(const char *key, void *dst, size_t dst_cap,
                         size_t *out_len);
/* Untyped put stores as BLOB (or empty blob). */
ta_kv_status_t ta_kv_put(const char *key, const void *src, size_t len);
ta_kv_status_t ta_kv_delete(const char *key);

ta_kv_status_t ta_kv_get_type(const char *key, uint32_t *out_type);
ta_kv_status_t ta_kv_put_typed(const char *key, uint32_t type, const void *src,
                               size_t len);
ta_kv_status_t ta_kv_put_bool(const char *key, int value);
ta_kv_status_t ta_kv_get_bool(const char *key, int *out_value);
ta_kv_status_t ta_kv_put_smallint(const char *key, int32_t value);
ta_kv_status_t ta_kv_get_smallint(const char *key, int32_t *out_value);
ta_kv_status_t ta_kv_put_i32(const char *key, int32_t value);
ta_kv_status_t ta_kv_get_i32(const char *key, int32_t *out_value);
ta_kv_status_t ta_kv_put_string(const char *key, const char *s, size_t len);
ta_kv_status_t ta_kv_put_blob(const char *key, const void *src, size_t len);

const uint8_t *ta_kv_image(size_t *out_len);
ta_kv_status_t ta_kv_load_image(const uint8_t *src, size_t len);
void ta_kv_install_factory(void);

ta_kv_status_t ta_kv_set_roster(const char *const *names, size_t n);
size_t ta_kv_roster_count(void);
ta_kv_status_t ta_kv_roster_at(size_t index, char *dst, size_t dst_cap,
                               size_t *out_len);

size_t ta_kv_count(void);
ta_kv_status_t ta_kv_key_at(size_t index, char *dst, size_t dst_cap,
                            size_t *out_len);
ta_kv_status_t ta_kv_val_at(size_t index, void *dst, size_t dst_cap,
                            size_t *out_len);

ta_kv_status_t ta_config_get_controller(char *dst, size_t dst_cap,
                                        size_t *out_len);
ta_kv_status_t ta_config_put_controller(const char *name);

#endif
