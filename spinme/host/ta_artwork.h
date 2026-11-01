/* Artwork path: calm post-filter, default-art suppress, album-change one-shots. */
#ifndef SPINME_TA_ARTWORK_H
#define SPINME_TA_ARTWORK_H

#include "ta_event.h"

#include <stddef.h>
#include <stdint.h>

#define TA_ART_DEFAULT_FP 0xDEC0ADu /* stand-in fingerprint for default art */

/* Target lores edge for calm decode / downscale (square). */
#define TA_ART_LORES 90

/* Q8: 256 == 1.0 */
#define TA_ART_Q8_ONE 256

/*
 * Calm: when min(w,h) >= TA_ART_LORES, box-down to LORESxLORES, Q8 quadratic
 * B-spline 2D uprez back, light desat. Smaller buffers keep a 3x3 box+desat.
 */
void ta_artwork_calm_rgba(uint8_t *rgba, size_t w, size_t h);

/* Box-average downsample RGBA8888. dst must hold dw*dh*4. Returns 0 or -1. */
int ta_artwork_box_down(const uint8_t *src, size_t sw, size_t sh, uint8_t *dst,
                        size_t dw, size_t dh);

/*
 * Separable quadratic B-spline uprez (Q8 weights). Approximates a mild
 * Gaussian reconstruction. dst must hold dw*dh*4. Returns 0 or -1.
 */
int ta_artwork_q8_quad_uprez(const uint8_t *src, size_t sw, size_t sh,
                             uint8_t *dst, size_t dw, size_t dh);

/*
 * Separable Gaussian blur in place. sigma_q8 is sigma in Q8 pixels
 * (e.g. 256 ~= 1.0). Returns 0 or -1.
 */
int ta_artwork_gauss_rgba(uint8_t *rgba, size_t w, size_t h, int sigma_q8);

/*
 * Separable Gaussian-weighted uprez from lores (reference quality).
 * sigma_src_q8 is kernel sigma in *source* pixels (Q8). Returns 0 or -1.
 */
int ta_artwork_gauss_uprez(const uint8_t *src, size_t sw, size_t sh,
                           uint8_t *dst, size_t dw, size_t dh,
                           int sigma_src_q8);

/* Sum of squared RGB diffs over n_px pixels (alpha ignored). */
uint64_t ta_artwork_rgb_sumsq(const uint8_t *a, const uint8_t *b, size_t n_px);

/* Returns 1 if fingerprint matches suppressed default art. */
int ta_artwork_is_default(uint32_t fingerprint);

/*
 * On album change: arm Scheduler oneshots for proactive poll and
 * time-remaining refresh. dst receives NET_POLL / DRAW_UPDATE.
 */
int ta_artwork_on_album_change(const char *net_dst, const char *draw_dst,
                               ta_session_id_t session, uint32_t time_remain_ms);

#endif
