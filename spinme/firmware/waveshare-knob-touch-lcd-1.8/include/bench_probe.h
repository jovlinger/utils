#pragma once

#include <stdint.h>

/* Time N=100 calls of uimk2_zlist_update_render_draw on the host
 * short_title_noscroll scene (solid RGBA, no px). Prints one
 * "BENCH update_render_draw ..." line. curr and next are each
 * UIMK2_FRAME_BYTES and are overwritten. */
bool bench_probe_short_title(uint8_t *curr, uint8_t *next);
