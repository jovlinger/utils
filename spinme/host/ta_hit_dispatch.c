#include "ta_hit_dispatch.h"

#include "ta_draw_events.h"
#include "ta_net_events.h"
#include "ta_registry.h"
#include "ta_router.h"

#include <stddef.h>

ta_hit_role_t ta_hit_walk(const ta_follow_chrome_t *chrome, int x, int y,
                          const uint16_t *shape_w, const uint16_t *shape_h) {
    size_t i;

    if (chrome == NULL || shape_w == NULL || shape_h == NULL) {
        return TA_HIT_NONE;
    }
    /* Nearest first (high index). */
    for (i = chrome->n; i > 0; i--) {
        size_t idx = i - 1;
        ta_uilayout_t w;
        int lx, ly;
        int bw, bh;

        if (!chrome->accept_hit[idx]) {
            continue;
        }
        w = chrome->uilo[idx];
        lx = ta_uilo_x(w);
        ly = ta_uilo_y(w);
        bw = (int)shape_w[idx];
        bh = (int)shape_h[idx];
        if (x < lx || y < ly || x >= lx + bw || y >= ly + bh) {
            continue;
        }
        switch (idx) {
        case TA_FOLLOW_TRANSPORT:
            return TA_HIT_TRANSPORT;
        case TA_FOLLOW_VOLUME:
            return TA_HIT_VOLUME;
        default:
            return TA_HIT_NONE;
        }
    }
    return TA_HIT_NONE;
}

int ta_react_touch(const ta_follow_chrome_t *chrome, uint16_t x, uint16_t y,
                   ta_session_id_t session, const uint16_t *shape_w,
                   const uint16_t *shape_h) {
    ta_hit_role_t role;
    ta_event_envelope_t env;

    role = ta_hit_walk(chrome, (int)x, (int)y, shape_w, shape_h);
    if (role == TA_HIT_NONE) {
        return 1;
    }
    ta_env_clear(&env);
    env.session_id = session;
    (void)ta_env_set_src(&env, TA_DRAW_NAME);
    if (role == TA_HIT_TRANSPORT) {
        env.event.type = TA_EV_CTRL_TOGGLE;
    } else {
        env.event.type = TA_EV_CTRL_VOLUME;
        env.event.u.ctrl_volume.mode = (uint8_t)TA_CTRL_VOL_NONE;
    }
    if (ta_registry_post(TA_CONTROLLER_NAME, &env) != 0) {
        return -1;
    }
    return 0;
}

int ta_react_rotate(int8_t steps, ta_session_id_t session) {
    ta_event_envelope_t env;

    ta_env_clear(&env);
    env.event.type = TA_EV_CTRL_VOLUME;
    env.session_id = session;
    (void)ta_env_set_src(&env, TA_DRAW_NAME);
    env.event.u.ctrl_volume.mode = (uint8_t)TA_CTRL_VOL_REL;
    env.event.u.ctrl_volume.delta = steps;
    if (ta_registry_post(TA_CONTROLLER_NAME, &env) != 0) {
        return -1;
    }
    return 0;
}
