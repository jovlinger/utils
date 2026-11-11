/* External wiring: shape function ENUM -> handler switch (no fn ptrs). */
#ifndef SPINME_TA_WIRE_H
#define SPINME_TA_WIRE_H

#include "ta_event.h"
#include "ta_shape_swap.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum {
    TA_FN_NONE = 0,
    TA_FN_TRANSPORT_TOGGLE = 1,
    TA_FN_VOLUME = 2,
    TA_FN_NAV = 3,       /* 12 oclock: enter selecting or commit */
    TA_FN_SWAP_STEP = 4, /* rotary while selecting */
    TA_FN_DEBUG = 5      /* 6 oclock: capture + Log dump */
} ta_fn_enum_t;

typedef struct ta_wire_ctx {
    ta_shape_swap_t *swap; /* optional; NAV/SWAP_STEP need it */
    int selecting;         /* 1 while chooser open */
    void (*on_nav_glyph)(int down); /* flip 12 oclock arrow; may be NULL */
    void (*on_selecting)(int on);   /* show/hide overlay; may be NULL */
} ta_wire_ctx_t;

void ta_wire_reset(ta_wire_ctx_t *ctx);
int ta_wire_touch(ta_wire_ctx_t *ctx, ta_fn_enum_t fn, ta_session_id_t session);
int ta_wire_rotary(ta_wire_ctx_t *ctx, ta_fn_enum_t fn, int8_t steps,
                   ta_session_id_t session);

#ifdef __cplusplus
}
#endif

#endif
