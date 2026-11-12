/* Write a pack66 framebuffer as an 8-bit RGB PNG (zlib). */
#ifndef SPINME_TA_PACK66_PNG_H
#define SPINME_TA_PACK66_PNG_H

#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Expand r6/g6/b6 to 8-bit; a2==0 -> black. Returns 0 on success. */
int ta_pack66_write_png(const char *path, uint16_t w, uint16_t h,
                        const ta_pack66_t *px);
/* Nearest-neighbor upscale (scale>=1) for readable stills of a 360 panel. */
int ta_pack66_write_png_scaled(const char *path, uint16_t w, uint16_t h,
                               const ta_pack66_t *px, unsigned scale);

/* Load 8-bit RGB PNG (filter None, non-interlaced) as written by this module.
 * On success sets out_w/out_h and mallocs out_rgb (w*h*3); caller frees. */
int ta_pack66_read_png_rgb(const char *path, uint16_t *out_w, uint16_t *out_h,
                           uint8_t **out_rgb);

/* Byte-identical RGB decode of two PNGs (same size). 0 = equal, 1 = differ,
 * -1 = IO/decode error. */
int ta_pack66_png_pixel_equal(const char *path_a, const char *path_b);

/* Blit a pack66 rect into a panel-sized framebuffer (stride = panel_w). */
void ta_pack66_blit_fb(ta_pack66_t *fb, uint16_t panel_w, uint16_t panel_h,
                       int x, int y, int w, int h, const ta_pack66_t *src,
                       int stride_px);

#ifdef __cplusplus
}
#endif

#endif
