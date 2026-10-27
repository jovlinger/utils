#pragma once

/* ESP32-S3 ROM TJpgDec. Decode JPEG MCU rectangles with integer
 * nearest-neighbor into a caller-owned RGBA8888 buffer (A forced opaque).
 */

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

struct RomJpegInfo {
  uint16_t src_w;
  uint16_t src_h;
  uint16_t out_w; /* after ROM scale */
  uint16_t out_h;
  uint16_t dst_w;
  uint16_t dst_h;
  uint8_t scale; /* 0=1/1 .. 3=1/8 */
  int jd_prepare;
  int jd_decomp;
  uint32_t decode_ms;
};

/* Decode jpeg into dst (dst_w * dst_h * 4). Pre-clears dst to opaque black.
 * Picks the coarsest ROM scale with out >= dst on both axes when possible
 * (else 1/1). MCU RGB888 blocks are NN-mapped into dst. */
bool rom_jpeg_decode_nn_rgba(const uint8_t *jpeg, size_t len, uint8_t *dst,
                             uint16_t dst_w, uint16_t dst_h, RomJpegInfo *info);
