#pragma once

#include <stdint.h>

/* 360x360 RGBA8888 Disintegration panel base, linked from
 * disintegration_360.rgba via bg_embed.S. No JPG decode on device. */
extern const uint8_t disintegration_360_rgba_start[] asm(
    "disintegration_360_rgba_start");
extern const uint8_t disintegration_360_rgba_end[] asm(
    "disintegration_360_rgba_end");
