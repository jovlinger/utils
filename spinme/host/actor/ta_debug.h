/* Debug / get_debug: glass snapshot + log lines. */
#ifndef SPINME_TA_DEBUG_H
#define SPINME_TA_DEBUG_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Format display/stack snapshot, ta_log_accept, then ta_log_dump. */
int ta_debug_capture_and_log(uint32_t now_ms);

/*
 * Build get_debug payload: ASCII header then pack66 pixels then log text.
 * Header: "w=%u&h=%u&fmt=pack66&px_n=%u&logs=%u\n"
 * Caller frees *out_bytes. Returns 0, or -1 on alloc failure.
 */
int ta_debug_build_get_debug(uint8_t **out_bytes, size_t *out_len);

#ifdef __cplusplus
}
#endif
#endif
