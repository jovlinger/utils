/* uimk2 implementation constants. Names follow spinme/DESIGN.md "Constants".
 *
 * The loops use the names; a board file sets the values. Every define is
 * guarded so a board header included before this one wins. The values here
 * are the current Waveshare settings.
 *
 * last_run, every, and expire_by count CLOCK_RES ticks.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_CONFIG_H
#define UIMK2_CONFIG_H

#ifndef PANEL_W
#define PANEL_W 360u /* framebuffer width in pixels */
#endif
#ifndef PANEL_H
#define PANEL_H 360u /* framebuffer height in pixels */
#endif

#ifndef QUEUE_DEPTH
#define QUEUE_DEPTH 8u /* event-ring slots */
#endif

#ifndef CLOCK_RES
#define CLOCK_RES 1u /* one tick of the absolute clock, in ms */
#endif
/* DESIGN.md calls this CLOCKS_PER_SEC; that name is taken by <time.h>. */
#ifndef CLOCKS_PER_SEC_TICKS
#define CLOCKS_PER_SEC_TICKS 1000u /* ticks in one logical second */
#endif

#ifndef POLL_EVERY_START
#define POLL_EVERY_START 1000u /* poll gap armed on wake */
#endif
#ifndef POLL_EVERY_MAX
#define POLL_EVERY_MAX 16000u /* poll gap cap */
#endif
#ifndef SCREEN_OFF_EVERY
#define SCREEN_OFF_EVERY 30000u /* backlight-off delay */
#endif
#ifndef UPDATE_RENDER_EVERY
#define UPDATE_RENDER_EVERY 200u /* update_render_draw cadence while awake */
#endif
#ifndef REDRAW_RETRY_EVERY
#define REDRAW_RETRY_EVERY 50u /* delay before a busy redraw is retried */
#endif
#ifndef REDRAW_ATTEMPT_CAP
#define REDRAW_ATTEMPT_CAP 5u /* busy redraws before ERROR */
#endif
#ifndef HIT_OPAQUE_PCT
#define HIT_OPAQUE_PCT 0u /* min opacity percent for an opaque hit, 0 = off */
#endif
#ifndef SCROLL_MS_PER_OX
/* Millis per px of SCROLL ox. 50 => 2x the prior 100 ms/px cadence. */
#define SCROLL_MS_PER_OX 50u
#endif

/* Default blit tile. Override before including uimk2_blit.h. Working set
 * is 2*TILE_W*TILE_H*4 bytes (src+dst); keep under the S3 D-cache. */
#ifndef TILE_W
#define TILE_W 32u
#endif
#ifndef TILE_H
#define TILE_H 32u
#endif

#endif /* UIMK2_CONFIG_H */
