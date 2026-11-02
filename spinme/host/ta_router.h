/* Controller Router: SetRoute only; all else forwards to current target. */
#ifndef SPINME_TA_ROUTER_H
#define SPINME_TA_ROUTER_H

#include "ta_event.h"

#define TA_CONTROLLER_NAME "Controller"

void ta_router_reset(void);
void ta_router_start(void); /* register as Controller */
int ta_router_enqueue(const ta_event_t *ev);
/* Empty string if none. */
const char *ta_router_current_target(void);

#endif
