/* Sorted KV image: contiguous entries linked by next offsets.
 *
 * Image head: uint32 first (0 = empty). Each live entry (offset >= 4):
 *   uint32 entrylen;   total bytes of this entry
 *   uint32 next;       offset of next entry, or 0
 *   uint16 keylen;
 *   uint8  key[keylen];
 *   uint32 valueinfo;  type in high 3 bits; see TA_KV_VTYPE_*
 *   uint8  value[];    length from valueinfo / type
 *
 * Keys are kept in ascending lexicographic order along the live chain.
 * next need not be adjacent (holes from unlink / first-fit reuse).
 * valueinfo types (high 3 bits): smallint 000, int32 001, string 011,
 * blob 100, bool 111. Low 29 bits: smallint payload, bool in bit0,
 * string/blob length; int32 uses value[0..3] LE.
 */
#ifndef SPINME_TA_KV_H
#define SPINME_TA_KV_H

#include <stddef.h>
#include <stdint.h>

#define TA_KV_KEY_MAX 32
#define TA_KV_VAL_MAX 1024
#define TA_KV_SLOTS 32

#define TA_KV_IMAGE_HEAD_SIZE 4u
/* entrylen u32 + next u32 + keylen u16 (key and valueinfo follow). */
#define TA_KV_REC_PREFIX_SIZE 10u
#define TA_KV_VALUEINFO_SIZE 4u

#define TA_KV_KEY_CONTROLLER "current_controller"
#define TA_KV_KEY_LOG_URL "log_receiver_url"
#define TA_KV_KEY_ACTORS "actors_to_start"

/* High 3 bits of valueinfo. */
#define TA_KV_VTYPE_SMALLINT 0u
#define TA_KV_VTYPE_INT32 1u
#define TA_KV_VTYPE_STRING 3u
#define TA_KV_VTYPE_BLOB 4u
#define TA_KV_VTYPE_BOOL 7u

#define TA_KV_VINFO_TYPE(vi) ((uint32_t)(vi) >> 29)
#define TA_KV_VINFO_PAYLOAD(vi) ((uint32_t)(vi) & 0x1fffffffu)
#define TA_KV_VINFO_PACK(type, payload)                                        \
    ((((uint32_t)(type) & 7u) << 29) | ((uint32_t)(payload) & 0x1fffffffu))

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
