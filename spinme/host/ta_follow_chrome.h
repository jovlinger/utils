/* Follow chrome UILayout placements (static paint-once + high-z clock/title). */
#ifndef SPINME_TA_FOLLOW_CHROME_H
#define SPINME_TA_FOLLOW_CHROME_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
/* Slot roles (index into built arrays). Z order: low index = farthest. */
enum {
    TA_FOLLOW_BASE = 0,
    TA_FOLLOW_ZONE = 1,
    TA_FOLLOW_ARTIST = 2,
    TA_FOLLOW_ALBUM = 3,
    TA_FOLLOW_TITLE = 4,
    TA_FOLLOW_VOLUME = 5,
    TA_FOLLOW_TRANSPORT = 6, /* play/stop at panel center */
    TA_FOLLOW_CLOCK = 7,
    TA_FOLLOW_NAV = 8, /* 12 oclock up/down (above SwapShape) */
    TA_FOLLOW_N = 9
};

typedef struct ta_follow_chrome {
    ta_uilayout_t uilo[TA_FOLLOW_N];
    uint8_t accept_hit[TA_FOLLOW_N]; /* parallel flags (choice from 0006) */
    uint8_t paint_once[TA_FOLLOW_N]; /* 1 = static chrome; leave after first push */
    size_t n;
} ta_follow_chrome_t;

/* Shape idxs: base..clock, then nav. */
int ta_follow_chrome_build(ta_follow_chrome_t *out, const unsigned shape_idx[TA_FOLLOW_N]);

/*
 * Text column at text_x/text_y; nav at 12 oclock (button_y, centered);
 * transport (play/stop) at panel center; clock in the text column under volume.
 */
typedef struct ta_follow_metrics {
    int panel_w;
    int panel_h;
    int text_x;
    int text_y;
    int text_h;
    int gap;
    int button_y;
    int transport_w;
    int transport_h;
    int nav_w;
    int nav_h;
} ta_follow_metrics_t;

/* Rewrite x/y of an already built chrome; keeps shape idx, dirty, flags. */
int ta_follow_chrome_place(ta_follow_chrome_t *chrome,
                           const ta_follow_metrics_t *m);

/* True if slot is high-z dynamic (clock or scrolling title). */
int ta_follow_is_high_z_dynamic(unsigned slot);

#ifdef __cplusplus
}
#endif
#endif
