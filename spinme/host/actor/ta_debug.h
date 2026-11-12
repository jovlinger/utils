/* Debug chrome: capture glass state into Logger and dump. */
#ifndef SPINME_TA_DEBUG_H
#define SPINME_TA_DEBUG_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Format display/stack snapshot, ta_log_accept, then ta_log_dump. */
int ta_debug_capture_and_log(uint32_t now_ms);

#ifdef __cplusplus
}
#endif
#endif
