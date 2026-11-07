/* react_touch/react_rotate: accept_hit walk -> ControlEvents to Router. */
#ifndef SPINME_TA_HIT_DISPATCH_H
#define SPINME_TA_HIT_DISPATCH_H

#include "ta_event.h"
#include "ta_follow_chrome.h"
#include "ta_wire.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef enum {
    TA_HIT_NONE = 0,
    TA_HIT_TRANSPORT = 1,
    TA_HIT_VOLUME = 2,
    TA_HIT_NAV = 3 /* 12 oclock up/down; wiring decides select vs page-up */
} ta_hit_role_t;

/* Glass installs its wire ctx so touch/rotary hit the ENUM switch. */
void ta_hit_set_wire(ta_wire_ctx_t *wire);

/* Nearest-first accept_hit box test. Returns role or TA_HIT_NONE. */
ta_hit_role_t ta_hit_walk(const ta_follow_chrome_t *chrome, int x, int y,
                          const uint16_t *shape_w, const uint16_t *shape_h);

/*
 * Map ISR touch/rotate into ControlEvent posted to Controller Router.
 * Touch: hit-test then TOGGLE/VOLUME. Rotate: VOLUME with steps in payload.
 * Returns 0 if posted, 1 if miss (no post), -1 on error.
 */
int ta_react_touch(const ta_follow_chrome_t *chrome, uint16_t x, uint16_t y,
                   ta_session_id_t session, const uint16_t *shape_w,
                   const uint16_t *shape_h);
int ta_react_rotate(int8_t steps, ta_session_id_t session);

#ifdef __cplusplus
}
#endif
#endif
