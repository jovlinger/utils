/* Boot TaskActor fabric on device (Init + registry + actor start hooks). */
#ifndef SPINME_TA_DEVICE_BOOT_H
#define SPINME_TA_DEVICE_BOOT_H

#ifdef __cplusplus
extern "C" {
#endif

/* Register Init entries, run starts, spawn fabric helper task. */
void ta_device_boot(void);

/* True after successful boot. */
int ta_device_fabric_up(void);

#ifdef __cplusplus
}
#endif

#endif
