/* Artwork path: calm post-filter, default-art suppress, album-change one-shots. */
#ifndef SPINME_TA_ARTWORK_H
#define SPINME_TA_ARTWORK_H

#include "ta_event.h"

#include <stddef.h>
#include <stdint.h>

#define TA_ART_DEFAULT_FP 0xDEC0ADu /* stand-in fingerprint for default art */

/* Box blur + light desat on RGBA8888 in place (calm). */
void ta_artwork_calm_rgba(uint8_t *rgba, size_t w, size_t h);

/* Returns 1 if fingerprint matches suppressed default art. */
int ta_artwork_is_default(uint32_t fingerprint);

/*
 * On album change: arm Scheduler oneshots for proactive poll and
 * time-remaining refresh. dst receives NET_POLL / DRAW_UPDATE.
 */
int ta_artwork_on_album_change(const char *net_dst, const char *draw_dst,
                               ta_session_id_t session, uint32_t time_remain_ms);

#endif
