/* Follow chrome UILayout placements (static paint-once + high-z clock/title). */
#ifndef SPINME_TA_FOLLOW_CHROME_H
#define SPINME_TA_FOLLOW_CHROME_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

/* Slot roles (index into built arrays). Z order: low index = farthest. */
enum {
    TA_FOLLOW_BASE = 0,
    TA_FOLLOW_ZONE = 1,
    TA_FOLLOW_ARTIST = 2,
    TA_FOLLOW_ALBUM = 3,
    TA_FOLLOW_TITLE = 4,
    TA_FOLLOW_VOLUME = 5,
    TA_FOLLOW_TRANSPORT = 6,
    TA_FOLLOW_CLOCK = 7,
    TA_FOLLOW_N = 8
};

typedef struct ta_follow_chrome {
    ta_uilayout_t uilo[TA_FOLLOW_N];
    uint8_t accept_hit[TA_FOLLOW_N]; /* parallel flags (choice from 0006) */
    uint8_t paint_once[TA_FOLLOW_N]; /* 1 = static chrome; leave after first push */
    size_t n;
} ta_follow_chrome_t;

/* Shape idxs: base, zone, artist, album, title, volume, transport, clock. */
int ta_follow_chrome_build(ta_follow_chrome_t *out, const unsigned shape_idx[TA_FOLLOW_N]);

/* True if slot is high-z dynamic (clock or scrolling title). */
int ta_follow_is_high_z_dynamic(unsigned slot);

#endif
