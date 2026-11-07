/* Outline / solid chrome icons (play, pause, up, down) in pack66. */
#ifndef SPINME_TA_CHROME_ICONS_H
#define SPINME_TA_CHROME_ICONS_H

#include "ta_uilayout.h"

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define TA_CHROME_ICON_PX 30

/* Clear to transparent, then stroke/fill. All operate on w*w buffers. */
void ta_chrome_icon_clear(ta_pack66_t *px, uint16_t w);
void ta_chrome_icon_play_outline(ta_pack66_t *px, uint16_t w);
void ta_chrome_icon_pause_outline(ta_pack66_t *px, uint16_t w);
void ta_chrome_icon_up_solid(ta_pack66_t *px, uint16_t w);
void ta_chrome_icon_down_solid(ta_pack66_t *px, uint16_t w);

#ifdef __cplusplus
}
#endif

#endif
