/* Image init loader: roster -> per-name blob -> stub load -> init(). */
#ifndef SPINME_TA_BOOT_H
#define SPINME_TA_BOOT_H

#include "ta_actor.h"

#define TA_BOOT_MAX 8

/* Load each roster name's blob (stub: any non-empty blob is a host actor)
 * and call init(). Returns the number started, or -1 on a hard failure.
 */
int ta_boot_from_kv(void);
/* exit() every actor this boot started, in reverse order. */
void ta_boot_exit_all(void);
int ta_boot_running_count(void);

#endif
