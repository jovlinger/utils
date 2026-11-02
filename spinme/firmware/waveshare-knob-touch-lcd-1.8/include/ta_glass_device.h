#pragma once

/* Device glue for the Draw glass owner (spinme/host/ta_draw_glass.h):
 * pack66 glyph atlas from glyphs.bin, panel-sized pack66 base in PSRAM,
 * and the backend seam (PSRAM alloc, QSPI exterior push, backlight pin,
 * wall clock). Call after panel_begin (glyph mmap) and before the Draw
 * task pumps DRAW_SET_SHAPE_STACK. */

#include <stdbool.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Build atlas + base, set backend + cfg on the glass. False on alloc fail. */
bool ta_glass_device_bind(void);

/* Convert straight RGBA8888 (panel-sized) into the base pack66 pixels.
 * Caller then posts DRAW_UPDATE [TA_DRAW_UPD_BASE_DIRTY] to Draw. */
void ta_glass_device_base_from_rgba(const uint8_t *rgba);

/* RGBA scratch the albumart decoder may target (panel-sized, PSRAM). */
uint8_t *ta_glass_device_rgba_scratch(void);

#ifdef __cplusplus
}
#endif
