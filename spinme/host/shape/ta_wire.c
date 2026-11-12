#include "ta_wire.h"

#ifndef SPINME_NO_DEBUG_CHROME
#include "ta_debug.h"
#endif
#include "ta_draw_events.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_router.h"

#include <stddef.h>

void ta_wire_reset(ta_wire_ctx_t *ctx) {
    if (ctx == NULL) {
        return;
    }
    ctx->selecting = 0;
}

static int post_toggle(ta_session_id_t session) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.session_id = session;
    (void)ta_env_set_src(&env, TA_DRAW_NAME);
    env.event.type = TA_EV_CTRL_TOGGLE;
    return ta_registry_post(TA_CONTROLLER_NAME, &env) == 0 ? 0 : -1;
}

static int post_volume(ta_session_id_t session, int8_t steps) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.session_id = session;
    (void)ta_env_set_src(&env, TA_DRAW_NAME);
    env.event.type = TA_EV_CTRL_VOLUME;
    if (steps == 0) {
        env.event.u.ctrl_volume.mode = (uint8_t)TA_CTRL_VOL_NONE;
        env.event.u.ctrl_volume.delta = 0;
    } else {
        env.event.u.ctrl_volume.mode = (uint8_t)TA_CTRL_VOL_REL;
        env.event.u.ctrl_volume.delta = steps;
    }
    return ta_registry_post(TA_CONTROLLER_NAME, &env) == 0 ? 0 : -1;
}

int ta_wire_touch(ta_wire_ctx_t *ctx, ta_fn_enum_t fn, ta_session_id_t session) {
    if (ctx == NULL) {
        return -1;
    }
    switch (fn) {
    case TA_FN_NONE:
        return 1;
    case TA_FN_TRANSPORT_TOGGLE:
        return post_toggle(session);
    case TA_FN_VOLUME:
        return post_volume(session, 0);
    case TA_FN_NAV:
        if (ctx->selecting) {
            /* External down/select: commit currently shown alternative. */
            ctx->selecting = 0;
            if (ctx->on_nav_glyph != NULL) {
                ctx->on_nav_glyph(0);
            }
            if (ctx->on_selecting != NULL) {
                ctx->on_selecting(0);
            }
            return 0;
        }
        if (ctx->swap == NULL || ctx->swap->n < 2) {
            /* Nothing to choose; still a hit. */
            return 0;
        }
        ctx->selecting = 1;
        if (ctx->on_nav_glyph != NULL) {
            ctx->on_nav_glyph(1);
        }
        if (ctx->on_selecting != NULL) {
            ctx->on_selecting(1);
        }
        return 0;
    case TA_FN_SWAP_STEP:
        return 1;
    case TA_FN_DEBUG:
#ifdef SPINME_NO_DEBUG_CHROME
        (void)session;
        return 0;
#else
        return ta_debug_capture_and_log(ta_now_ms());
#endif
    default:
        return -1;
    }
}

int ta_wire_rotary(ta_wire_ctx_t *ctx, ta_fn_enum_t fn, int8_t steps,
                   ta_session_id_t session) {
    if (ctx == NULL || steps == 0) {
        return 1;
    }
    switch (fn) {
    case TA_FN_SWAP_STEP:
        if (!ctx->selecting || ctx->swap == NULL || ctx->swap->n == 0) {
            return 1;
        }
        {
            unsigned next = ctx->swap->active;

            if (steps > 0) {
                next = (next + (unsigned)steps) % ctx->swap->n;
            } else {
                unsigned back = (unsigned)(-steps) % ctx->swap->n;

                next = (next + ctx->swap->n - back) % ctx->swap->n;
            }
            return ta_shape_swap_set_active(ctx->swap, next) == 0 ? 0 : -1;
        }
    case TA_FN_VOLUME:
    case TA_FN_NONE:
        return post_volume(session, steps);
    default:
        return post_volume(session, steps);
    }
}
