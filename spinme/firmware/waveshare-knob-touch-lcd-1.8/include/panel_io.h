#pragma once

#include <stddef.h>
#include <stdint.h>

bool panel_begin(void);
/* Two PSRAM frames. Draw calls land in the back frame until panel_present. */
bool panel_buffers_begin(void);
/* One straight-alpha RGBA8888 span, RGB only (alpha is not blended here).
 * row points at the first pixel, 4 bytes each. */
void panel_push_rgba_span(int x, int y, int w, const uint8_t *row);
void panel_present(void);
void panel_cmd(uint8_t cmd, const uint8_t *data, size_t len);
void panel_fill_screen(uint16_t color565);
void panel_fill_rect(int x, int y, int w, int h, uint16_t color565);
void panel_text(int x, int y, const char *s, int scale, uint16_t color565);
/* Draw glyphs over existing pixels. ink_scale is 0..255 of the glyph alpha. */
void panel_text_over(int x, int y, const char *s, int scale, uint16_t color565,
                     int ink_scale);
/* Width includes one pixel after every character. */
int panel_text_width(const char *s);
/* Ink and paper for the glyph span only. Does not paint the rest of the row. */
void panel_text_on(int x, int y, const char *s, int scale, uint16_t ink565,
                   uint16_t paper565);
