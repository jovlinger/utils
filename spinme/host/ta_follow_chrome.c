#include "ta_follow_chrome.h"

#include <string.h>

/* Rough follow placements on 360x360 (product salvage; not final art). */
static const int k_xy[TA_FOLLOW_N][2] = {
    {0, 0},     /* base full-bleed */
    {20, 40},   /* zone */
    {20, 70},   /* artist */
    {20, 100},  /* album */
    {20, 140},  /* title (scroll) */
    {20, 280},  /* volume */
    {140, 300}, /* transport */
    {120, 20},  /* clock */
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
    /* Hit targets: transport + volume. */
    out->accept_hit[TA_FOLLOW_TRANSPORT] = 1;
    out->accept_hit[TA_FOLLOW_VOLUME] = 1;
    /* Clock and title nearest (already last in array). */
    return 0;
}

int ta_follow_is_high_z_dynamic(unsigned slot) {
    return slot == TA_FOLLOW_CLOCK || slot == TA_FOLLOW_TITLE;
}
