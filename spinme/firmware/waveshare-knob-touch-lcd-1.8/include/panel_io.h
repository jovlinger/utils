#pragma once

#include <stddef.h>
#include <stdint.h>

bool panel_begin(void);
/* Two PSRAM frames. Draw calls land in the back frame until panel_present. */
bool panel_buffers_begin(void);
void panel_present(void);
void panel_cmd(uint8_t cmd, const uint8_t *data, size_t len);
void panel_fill_screen(uint16_t color565);
void panel_fill_rect(int x, int y, int w, int h, uint16_t color565);
void panel_text(int x, int y, const char *s, int scale, uint16_t color565);
/* Width includes one pixel after every character. */
int panel_text_width(const char *s);
/* Ink and paper for the glyph span only. Does not paint the rest of the row. */
void panel_text_on(int x, int y, const char *s, int scale, uint16_t ink565,
                   uint16_t paper565);
