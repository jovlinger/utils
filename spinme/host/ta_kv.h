/* Dead-simple KV image: packed singly linked records.
 *
 * next_ptr convention (little-endian offsets from the image base):
 *   bytes [0,4) are a uint32 head. 0 means the live list is empty.
 *   each live record starts at offset >= 4:
 *     uint32 next;      0 means end of list (0 is never a record)
 *     uint16 key_len;
 *     uint32 blob_len;
 *     uint8  key[key_len];
 *     uint8  blob[blob_len];
 *   No key order. No padding between fields.
 *   v1 put appends at the high-water mark. Replacing a value that does not
 *   fit in the old record unlinks it and appends; the old span is a hole
 *   until a later first-fit allocator reuses it.
 */
#ifndef SPINME_TA_KV_H
#define SPINME_TA_KV_H

#include <stddef.h>
#include <stdint.h>

#define TA_KV_KEY_MAX 32
#define TA_KV_VAL_MAX 256
#define TA_KV_SLOTS 32

#define TA_KV_IMAGE_HEAD_SIZE 4u
#define TA_KV_REC_HDR_SIZE 10u /* next u32 + key_len u16 + blob_len u32 */

#define TA_KV_KEY_CONTROLLER "current_controller"
/* Start roster blob is a list of actor names; encoding is locked later. */
#define TA_KV_KEY_ACTORS "actors_to_start"

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

/* Live image bytes (header + records up to the high-water mark). */
const uint8_t *ta_kv_image(size_t *out_len);
/* Replace the live image. len is the high-water mark (includes holes). */
ta_kv_status_t ta_kv_load_image(const uint8_t *src, size_t len);
/* Static-build defaults: roster plus one blob per named actor. Writable after. */
void ta_kv_install_factory(void);

/* Config facade helpers. */
ta_kv_status_t ta_config_get_controller(char *dst, size_t dst_cap,
                                        size_t *out_len);
ta_kv_status_t ta_config_put_controller(const char *name);

#endif
