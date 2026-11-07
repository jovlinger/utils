#include "ta_follow_chrome.h"

#include <string.h>

/* Rough follow placements on 360x360 (overwritten by place()). */
static const int k_xy[TA_FOLLOW_N][2] = {
    {0, 0},     /* base */
    {20, 40},   /* zone */
    {20, 70},   /* artist */
    {20, 100},  /* album */
    {20, 140},  /* title */
    {20, 280},  /* volume */
    {165, 165}, /* transport center */
    {20, 310},  /* clock */
    {165, 12},  /* nav 12 oclock */
};

int ta_follow_chrome_build(ta_follow_chrome_t *out,
                           const unsigned shape_idx[TA_FOLLOW_N]) {
    size_t i;

    if (out == NULL || shape_idx == NULL) {
        return -1;
    }
    memset(out, 0, sizeof(*out));
    out->n = TA_FOLLOW_N;
    for (i = 0; i < TA_FOLLOW_N; i++) {
        out->uilo[i] =
            ta_uilo_make(1, k_xy[i][0], k_xy[i][1], shape_idx[i]);
        out->paint_once[i] = ta_follow_is_high_z_dynamic((unsigned)i) ? 0 : 1;
        out->accept_hit[i] = 0;
    }
    /* Hit targets: transport + volume + nav. */
    out->accept_hit[TA_FOLLOW_TRANSPORT] = 1;
    out->accept_hit[TA_FOLLOW_VOLUME] = 1;
    out->accept_hit[TA_FOLLOW_NAV] = 1;
    return 0;
}

static ta_uilayout_t move_to(ta_uilayout_t w, int x, int y) {
    return ta_uilo_make(ta_uilo_dirty(w), x, y, ta_uilo_shape(w));
}

int ta_follow_chrome_place(ta_follow_chrome_t *chrome,
                           const ta_follow_metrics_t *m) {
    int y;
    int tx;
    static const unsigned lines[5] = {TA_FOLLOW_ZONE, TA_FOLLOW_ARTIST,
                                      TA_FOLLOW_ALBUM, TA_FOLLOW_TITLE,
                                      TA_FOLLOW_VOLUME};
    size_t i;

    if (chrome == NULL || m == NULL || chrome->n != TA_FOLLOW_N ||
        m->text_h <= 0) {
        return -1;
    }
    y = m->text_y;
    for (i = 0; i < 5; i++) {
        chrome->uilo[lines[i]] = move_to(chrome->uilo[lines[i]], m->text_x, y);
        y += m->text_h + m->gap;
    }
    /* Clock stays in the text column after volume. */
    chrome->uilo[TA_FOLLOW_CLOCK] = move_to(chrome->uilo[TA_FOLLOW_CLOCK],
                                            m->text_x, y + m->gap);
    /* Nav at 12 oclock (top center). */
    tx = (m->panel_w - m->nav_w) / 2;
    if (tx < 0) {
        tx = 0;
    }
    chrome->uilo[TA_FOLLOW_NAV] =
        move_to(chrome->uilo[TA_FOLLOW_NAV], tx, m->button_y);
    /* Play/stop at panel center. */
    tx = (m->panel_w - m->transport_w) / 2;
    if (tx < 0) {
        tx = 0;
    }
    {
        int ty = 0;

        if (m->panel_h > 0) {
            ty = (m->panel_h - m->transport_h) / 2;
            if (ty < 0) {
                ty = 0;
            }
        }
        chrome->uilo[TA_FOLLOW_TRANSPORT] =
            move_to(chrome->uilo[TA_FOLLOW_TRANSPORT], tx, ty);
    }
    chrome->uilo[TA_FOLLOW_BASE] = move_to(chrome->uilo[TA_FOLLOW_BASE], 0, 0);
    return 0;
}

int ta_follow_is_high_z_dynamic(unsigned slot) {
    return slot == TA_FOLLOW_CLOCK || slot == TA_FOLLOW_TITLE;
}
