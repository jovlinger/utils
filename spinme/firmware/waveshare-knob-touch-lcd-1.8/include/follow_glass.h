#pragma once

/* Follow-view picture on the host zlist. Zone, transport, artist, album,
 * title, and three volume digits. Desired digits are pre-blended at alpha
 * 128 into their own shape so the zlist replace-blit still shows the overlay.
 *
 * Player HTTP is not here. The strings and the polled volume are stand-ins
 * until a poll handler writes them.
 */

#include <stdbool.h>
#include <stdint.h>

extern "C" {
#include "uimk2_event.h"
#include "uimk2_zlist.h"
}

/* Index 0 is closest. The transport button accepts hits. */
enum {
  FOLLOW_TRANSPORT = 0,
  FOLLOW_DESIRE = 1,
  FOLLOW_VOLUME = 2,
  FOLLOW_TITLE = 3,
  FOLLOW_ALBUM = 4,
  FOLLOW_ARTIST = 5,
  FOLLOW_ZONE = 6,
  FOLLOW_BASE = 7,
  FOLLOW_COUNT = 8
};

bool follow_glass_build(uimk2_zlist *z, uint8_t *curr, uint8_t *next,
                        uimk2_ring *ring, uimk2_zlist_ping_fn ping, void *ctx);

/* Rewrite the button, the polled digits, and the desired overlay.
 * desired_on is false when the overlay should match the polled digits. */
void follow_glass_raster(int polled, int desired, bool playing, bool desired_on);
