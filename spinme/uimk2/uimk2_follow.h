/* Host follow view on uimk2.
 *
 * The picture is the glass follow view: a transport button, a zone line,
 * artist and album, a title, and a three-digit volume. A desired volume
 * that differs from the polled volume is drawn over those digits at alpha
 * 128. Zone, transport, and volume are fixed slots below static_top.
 * Artist and album sit in the album region; the title sits at song_mark.
 *
 * The glass sources this replaces are on branch 8deb163b-two-core-spinme-glass.
 * Tag circui-pre-uimk2 does not contain them. It contains circui/MANUAL.md
 * and the same firmware scaffold this branch already has.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_FOLLOW_H
#define UIMK2_FOLLOW_H

#include <stdbool.h>
#include <stdint.h>

#include "uimk2_arena.h"
#include "uimk2_bitmap.h"
#include "uimk2_line.h"
#include "uimk2_sched.h"

#define UIMK2_FOLLOW_TEXT 48u

typedef struct {
    uimk2_bmtab bm;
    uimk2_arena arena;
    uimk2_sched *sched; /* optional */
    uint8_t *screen;
    uint16_t sw, sh;
    uint16_t root;
    uint16_t button; /* white RGBA, stable rect */
    uimk2_line zone;
    uimk2_line play;
    uimk2_line stop;
    uimk2_line volume;
    uimk2_line desired;
    uimk2_line artist;
    uimk2_line album;
    uimk2_line title;
    int button_x, button_y, button_w, button_h;
    int volume_x, volume_y;
    int vol;
    int desired_vol;
    bool overlay;
    bool showing_stop; /* button label is "stop" while the player is playing */
    char artist_s[UIMK2_FOLLOW_TEXT];
    char album_s[UIMK2_FOLLOW_TEXT];
    char title_s[UIMK2_FOLLOW_TEXT];
    uimk2_layout_item items[8];
    uint16_t nitems;
} uimk2_follow;

/* Fixed slots, then an empty artist / album / title. False when the arena
 * or the header table cannot hold the fixed slots. screen is sw*sh*4. */
bool uimk2_follow_init(uimk2_follow *f, uimk2_bm *storage, uint16_t cap,
                       void *arena_buf, uint32_t arena_cap, uint8_t *screen,
                       uint16_t sw, uint16_t sh);

void uimk2_follow_set_sched(uimk2_follow *f, uimk2_sched *sched);

/* Artist or album change rewinds to album_mark and rebuilds the title.
 * A title-only change rewinds to song_mark. Identical text does nothing.
 * False when the lines do not fit. */
bool uimk2_follow_set_text(uimk2_follow *f, const char *artist,
                           const char *album, const char *title);

/* Player status. "play" paints the button label "stop". Anything else
 * paints "play". The button rect does not move. */
void uimk2_follow_set_status(uimk2_follow *f, const char *status);

/* Polled volume, 0..100. Overlay hides when this equals the desired. */
void uimk2_follow_set_volume(uimk2_follow *f, int volume);

/* Follow-view detent: move desired, show the overlay, post SetVolume,
 * and restart the clocks when a sched is attached. */
bool uimk2_follow_knob(uimk2_follow *f, int delta, uint32_t now_ms);

/* A touch inside the button posts Touch and Toggle. Returns whether the
 * point hit the button. */
bool uimk2_follow_touch(uimk2_follow *f, int x, int y, uint32_t now_ms);

/* Apply a poll snapshot. Does not restart the clocks. */
bool uimk2_follow_snapshot(uimk2_follow *f, const char *artist,
                           const char *album, const char *title, int volume);

uimk2_rect uimk2_follow_repaint(uimk2_follow *f);

#endif /* UIMK2_FOLLOW_H */
