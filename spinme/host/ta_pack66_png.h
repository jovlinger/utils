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

/* Blit a pack66 rect into a panel-sized framebuffer (stride = panel_w). */
void ta_pack66_blit_fb(ta_pack66_t *fb, uint16_t panel_w, uint16_t panel_h,
                       int x, int y, int w, int h, const ta_pack66_t *src,
                       int stride_px);

#ifdef __cplusplus
}
#endif

#endif
