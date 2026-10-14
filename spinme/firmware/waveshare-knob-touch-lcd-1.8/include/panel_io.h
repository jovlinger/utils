#pragma once

#include <stddef.h>
#include <stdint.h>

bool panel_begin(void);
void panel_cmd(uint8_t cmd, const uint8_t *data, size_t len);
void panel_fill_screen(uint16_t color565);
void panel_text(int x, int y, const char *s, int scale, uint16_t color565);
