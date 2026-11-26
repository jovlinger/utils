#include "ta_hit_dispatch.h"

#include "ta_wire.h"

#include <stddef.h>

/* Optional process-wide wire context; glass installs before paint/input. */
static ta_wire_ctx_t *g_wire;

void ta_hit_set_wire(ta_wire_ctx_t *wire) {
    g_wire = wire;
}

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
        case TA_FOLLOW_NAV:
            return TA_HIT_NAV;
        case TA_FOLLOW_DEBUG:
            return TA_HIT_DEBUG;
        default:
            return TA_HIT_NONE;
        }
    }
    return TA_HIT_NONE;
}

static ta_fn_enum_t fn_for_role(const ta_follow_chrome_t *chrome,
                                ta_hit_role_t role) {
    size_t idx;

    switch (role) {
    case TA_HIT_TRANSPORT:
        idx = TA_FOLLOW_TRANSPORT;
        break;
    case TA_HIT_VOLUME:
        idx = TA_FOLLOW_VOLUME;
        break;
    case TA_HIT_NAV:
        idx = TA_FOLLOW_NAV;
        break;
    case TA_HIT_DEBUG:
        idx = TA_FOLLOW_DEBUG;
        break;
    default:
        return TA_FN_NONE;
    }
    if (chrome == NULL || idx >= chrome->n) {
        return TA_FN_NONE;
    }
    return (ta_fn_enum_t)chrome->fn_enum[idx];
}

int ta_react_touch(const ta_follow_chrome_t *chrome, uint16_t x, uint16_t y,
                   ta_session_id_t session, const uint16_t *shape_w,
                   const uint16_t *shape_h) {
    ta_hit_role_t role;
    ta_fn_enum_t fn;
    ta_wire_ctx_t local;

    role = ta_hit_walk(chrome, (int)x, (int)y, shape_w, shape_h);
    if (role == TA_HIT_NONE) {
        return 1;
    }
    fn = fn_for_role(chrome, role);
    if (g_wire != NULL) {
        return ta_wire_touch(g_wire, fn, session);
    }
    ta_wire_reset(&local);
    return ta_wire_touch(&local, fn, session);
}

int ta_react_rotate(int8_t steps, ta_session_id_t session) {
    ta_wire_ctx_t local;
    ta_fn_enum_t fn = TA_FN_VOLUME;

    if (g_wire != NULL) {
        if (g_wire->selecting) {
            fn = TA_FN_SWAP_STEP;
        }
        return ta_wire_rotary(g_wire, fn, steps, session);
    }
    ta_wire_reset(&local);
    return ta_wire_rotary(&local, fn, steps, session);
}
