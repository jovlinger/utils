/* uimk2 glyph font table, generated on the host by gen_glyphs.py.
 *
 * Every glyph box is uimk2_glyph_h rows tall with its baseline on row
 * uimk2_glyph_b (rows 0..b-1 are above the baseline). A box is as wide as
 * its ink; a codepoint with no ink takes its advance width. Alpha is
 * coverage, filled * 255 / 64 of an 8x8 sample grid per pixel; RGB is
 * white and is not stored.
 *
 * uimk2_glyph_table is sorted by codepoint. Entry i's alpha is
 * width * uimk2_glyph_h bytes, row-major, at uimk2_glyph_alpha + offset.
 *
 * Portable C99, no platform headers.
 */
#ifndef UIMK2_GLYPHS_H
#define UIMK2_GLYPHS_H

#include <stdint.h>

typedef struct {
    uint32_t codepoint;
    uint16_t width;
    uint32_t offset;
} uimk2_glyph_entry;

extern const uint16_t uimk2_glyph_h;
extern const uint16_t uimk2_glyph_b;
extern const uint16_t uimk2_glyph_count;
extern const uimk2_glyph_entry uimk2_glyph_table[];
extern const uint8_t uimk2_glyph_alpha[];

#endif /* UIMK2_GLYPHS_H */
