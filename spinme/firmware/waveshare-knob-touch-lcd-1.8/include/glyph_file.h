#pragma once

#include <stdint.h>

#include "layout_box.h"

/* glyphs.bin, little-endian, mapped from flash (no RAM copy):
 * u32 magic 'GLY1', version, count, height,
 * letter_hshim, word_hshim, line_vshim, section_vshim,
 * index_off, reserved.
 * index: count * (u32 key, u32 offset)
 * record: u32 key, i16 x, i16 y, u16 w, u16 h, rgba[w*h*4]
 * Keep this in step with screenmock/glyphfile.py.
 */

/* Map the linked glyph file. Pixels stay in the flash mapping. */
bool glyph_file_mmap(void);

int glyph_body_h(void);
/* Zero-area boxes. Horizontal shims have height 0. Vertical shims have width 0. */
LayBox glyph_letter_hshim(void);
LayBox glyph_word_hshim(void);
LayBox glyph_line_vshim(void);
LayBox glyph_section_vshim(void);

/* One line: glyph boxes and the shims between them.
 * rgba[i] is null for a shim. Returns the item count, or 0 if nothing to draw. */
int glyph_line_items(const char *s, LayBox *boxes, const uint8_t **rgba, int cap);

/* l2r of those items, bottom-aligned. Returns 0 when the line has no glyphs. */
int glyph_line_size(const char *s, int *w, int *h);
