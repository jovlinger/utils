/* Boot TaskActor fabric on device (Init + registry + actor start hooks). */
#ifndef SPINME_TA_DEVICE_BOOT_H
#define SPINME_TA_DEVICE_BOOT_H

#include <stdint.h>

#include "ta_queue.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Register Init entries, run starts, bind Draw's queue, spawn fabric helper
 * task, post SET_ROUTE + SET_ACTIVE (lands in Draw's queue as
 * DRAW_SET_SHAPE_STACK until the Draw task pumps). */
void ta_device_boot(void);

/* Draw's MP/SC queue (consumed only by the Draw task via ta_draw_pump). */
ta_queue_t *ta_device_draw_queue(void);

/* True after successful boot. */
int ta_device_fabric_up(void);

/* Advance Scheduler real time. Call from the ONE task that runs the actor
 * fabric (registry posts run on the caller; Net completions must share it). */
void ta_device_tick_ms(uint32_t now_ms);

#ifdef __cplusplus
}
#endif

#endif
