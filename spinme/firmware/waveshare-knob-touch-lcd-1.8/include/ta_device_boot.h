/* Boot TaskActor fabric on device (Init + registry + actor start hooks). */
#ifndef SPINME_TA_DEVICE_BOOT_H
#define SPINME_TA_DEVICE_BOOT_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Register Init entries, run starts, spawn fabric helper task. */
void ta_device_boot(void);

/* True after successful boot. */
int ta_device_fabric_up(void);

/* Advance Scheduler real time. Call from the ONE task that runs the actor
 * fabric (registry posts run on the caller; Net completions must share it). */
void ta_device_tick_ms(uint32_t now_ms);

#ifdef __cplusplus
}
#endif

#endif
