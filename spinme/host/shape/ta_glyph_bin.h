/* Host loader for firmware glyphs.bin (GLY1) -> pack66 atlas + map. */
#ifndef SPINME_TA_GLYPH_BIN_H
#define SPINME_TA_GLYPH_BIN_H

#include "ta_text.h"
#include "ta_uilayout.h"

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct ta_glyph_bin {
    ta_shape_bitmap_t glyphs[95]; /* ascii 32..126 */
    ta_pack66_t *px_store;        /* owned blob of all glyph pixels */
    size_t px_cap;
    size_t px_used;
    ta_glyph_map_t map;
    int8_t kern[95]; /* letter shim; kern[0]=0 like device */
    uint16_t text_h;
    uint16_t word_shim_w;
    int ready;
} ta_glyph_bin_t;

void ta_glyph_bin_reset(ta_glyph_bin_t *gb);
/* Load path; installs shapes at idx 1..95 into the shape table. -1 on fail. */
int ta_glyph_bin_load(ta_glyph_bin_t *gb, const char *path);
void ta_glyph_bin_fini(ta_glyph_bin_t *gb);

/* Load 360x360 RGBA8888 boot art into pack66 base (opaque). */
int ta_base_from_rgba_file(ta_pack66_t *dst, uint16_t w, uint16_t h,
                           const char *path);

#ifdef __cplusplus
}
#endif

#endif
