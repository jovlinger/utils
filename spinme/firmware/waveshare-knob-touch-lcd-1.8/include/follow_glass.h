#pragma once

/* Follow-view picture on the host zlist. Zone, transport, clock,
 * artist, album, title, and three volume digits. The only panel-sized
 * preallocated pixmap is FOLLOW_BASE.px (opaque RGBA; boot Disintegration;
 * albumart NN). It is a normal zlist shape (is_base), not a side buffer.
 * Desired digits are pre-blended at alpha 128 into their own shape.
 *
 * Update selectors (switch on the shape): FIXED, SCROLL, CLOCKTEXT.
 * CLOCKTEXT only rewrites shape.text from the system clock (clock_tick);
 * the clock scheduler event refreshes that tick every UPDATE_RENDER_EVERY.
 * SCROLL sets ox = (clock_tick/SCROLL_MS_PER_OX) % pw over a full-width
 * text map (map wider than the viewport; trailing paper gap at wrap).
 *
 * Raster bakes L2R text maps into px (update does not write pixels).
 * follow_glass_set_track replaces artist/album/title and rewinds ox.
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
  FOLLOW_CLOCK = 3,
  FOLLOW_TITLE = 4,
  FOLLOW_ALBUM = 5,
  FOLLOW_ARTIST = 6,
  FOLLOW_ZONE = 7,
  FOLLOW_BASE = 8,
  FOLLOW_COUNT = 9
};

bool follow_glass_build(uimk2_zlist *z, uint8_t *curr, uint8_t *next,
                        uimk2_ring *ring, uimk2_zlist_ping_fn ping, void *ctx);

/* Copy artist, album, and title. Null becomes empty. Raster paints them. */
void follow_glass_set_track(const char *artist, const char *album,
                            const char *title);

/* Rewrite the button, the polled digits, and the desired overlay.
 * desired_on is false when the overlay should match the polled digits. */
void follow_glass_raster(int polled, int desired, bool playing, bool desired_on);

/* FOLLOW_BASE.px -- sole panel pixmap. Null before build. */
uint8_t *follow_glass_bg_rgba(void);

/* After writing FOLLOW_BASE.px, mark that shape dirty for the next URD. */
void follow_glass_bg_mark_dirty(void);
