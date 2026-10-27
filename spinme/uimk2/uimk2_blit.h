/* Tiled straight-alpha RGBA8888 src-over, and packed RGB666+A2 blit.
 *
 * pack66 word:
 *   A2 != 0: bits 0..7 / 8..15 / 16..23 = 00RRRRRR / 00GGGGGG / 00BBBBBB,
 *            bits 24..25 = opacity (1=25%, 2=50%, 3=100%).
 *   A2 == 0: transparent skip; bits 0..23 = run length in words to the next
 *            non-transparent pixel (1 .. 0xFFFFFF). Blit advances by that.
 *
 * L2R text bake writes pack66 with skips into the Cache store.
 * pack66 spans use PIE 128-bit load/store on ESP32-S3 for opaque runs.
 */
#ifndef UIMK2_BLIT_H
#define UIMK2_BLIT_H

#include "uimk2_config.h"

#include <stddef.h>
#include <stdint.h>

#define UIMK2_BLIT_TILE_WORKING_BYTES (2u * TILE_W * TILE_H * 4u)

#define UIMK2_BLIT_RGB6_MASK 0x003F3F3Fu
#define UIMK2_BLIT_A2_SHIFT 24
#define UIMK2_BLIT_A2_MASK (3u << UIMK2_BLIT_A2_SHIFT)
#define UIMK2_BLIT_SKIP_MASK 0x00FFFFFFu

void uimk2_blit_src_over_pixel(uint8_t *dst, const uint8_t *src);

void uimk2_blit_src_over_tile(uint8_t *dst, uint32_t dst_stride_px,
                              const uint8_t *src, uint32_t src_stride_px,
                              uint32_t x0, uint32_t y0, uint32_t tw,
                              uint32_t th);

void uimk2_blit_src_over(uint8_t *dst, uint32_t dst_stride_px,
                         const uint8_t *src, uint32_t src_stride_px,
                         uint32_t w, uint32_t h, uint32_t tile_w,
                         uint32_t tile_h);

uint32_t uimk2_blit_pack66(const uint8_t rgba[4]);
void uimk2_blit_unpack66(uint32_t p, uint8_t rgba[4]);

/* True when the word is a transparent skip (A2 == 0). */
static inline int uimk2_blit_is_skip66(uint32_t p) {
    return (p & UIMK2_BLIT_A2_MASK) == 0u;
}

/* Skip length in words; 0 is treated as 1. */
static inline uint32_t uimk2_blit_skip66(uint32_t p) {
    uint32_t n = p & UIMK2_BLIT_SKIP_MASK;
    return n == 0u ? 1u : n;
}

uint32_t uimk2_blit_lerp66(uint32_t dst, uint32_t src);

/* Coalesce A2==0 runs on one row: first word holds the run length. */
void uimk2_blit_encode_row_skips(uint32_t *row, uint32_t w);

/* Pack an RGBA8888 row into pack66 and encode transparent skips. */
void uimk2_blit_rgba_row_to_pack66(uint32_t *dst, const uint8_t *rgba,
                                   uint32_t w);

void uimk2_blit_src_over66(uint32_t *dst, uint32_t dst_stride_px,
                           const uint32_t *src, uint32_t src_stride_px,
                           uint32_t w, uint32_t h, uint32_t tile_w,
                           uint32_t tile_h);

#endif /* UIMK2_BLIT_H */
