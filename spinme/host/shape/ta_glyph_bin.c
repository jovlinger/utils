#include "ta_glyph_bin.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static uint32_t rd32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) |
           ((uint32_t)p[3] << 24);
}

static uint16_t rd16(const uint8_t *p) {
    return (uint16_t)p[0] | ((uint16_t)p[1] << 8);
}

static uint8_t a2_of(uint8_t alpha) {
    if (alpha >= 192) {
        return 3;
    }
    if (alpha >= 128) {
        return 2;
    }
    if (alpha >= 64) {
        return 1;
    }
    return 0;
}

void ta_glyph_bin_reset(ta_glyph_bin_t *gb) {
    if (gb == NULL) {
        return;
    }
    free(gb->px_store);
    memset(gb, 0, sizeof(*gb));
}

void ta_glyph_bin_fini(ta_glyph_bin_t *gb) {
    ta_glyph_bin_reset(gb);
}

static ta_pack66_t *alloc_px(ta_glyph_bin_t *gb, size_t n) {
    ta_pack66_t *p;

    if (gb->px_used + n > gb->px_cap) {
        return NULL;
    }
    p = gb->px_store + gb->px_used;
    gb->px_used += n;
    return p;
}

int ta_glyph_bin_load(ta_glyph_bin_t *gb, const char *path) {
    FILE *fp;
    uint8_t *file = NULL;
    long fsz;
    uint32_t magic;
    uint32_t ver;
    uint32_t count;
    uint32_t height;
    uint32_t letter_shim;
    uint32_t word_shim;
    uint32_t index_off;
    size_t i;
    size_t need_px = 0;

    if (gb == NULL || path == NULL) {
        return -1;
    }
    ta_glyph_bin_reset(gb);
    fp = fopen(path, "rb");
    if (fp == NULL) {
        return -1;
    }
    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return -1;
    }
    fsz = ftell(fp);
    if (fsz < 40) {
        fclose(fp);
        return -1;
    }
    rewind(fp);
    file = (uint8_t *)malloc((size_t)fsz);
    if (file == NULL || fread(file, 1, (size_t)fsz, fp) != (size_t)fsz) {
        free(file);
        fclose(fp);
        return -1;
    }
    fclose(fp);

    magic = rd32(file + 0);
    ver = rd32(file + 4);
    count = rd32(file + 8);
    height = rd32(file + 12);
    letter_shim = rd32(file + 16);
    word_shim = rd32(file + 20);
    index_off = rd32(file + 32);
    if (magic != 0x31594c47u || ver != 1 || count == 0 ||
        index_off + count * 8u > (uint32_t)fsz) {
        free(file);
        return -1;
    }
    (void)height;

    /* Pass 1: size pixel store. */
    for (i = 0; i < count; i++) {
        uint32_t key = rd32(file + index_off + i * 8u);
        uint32_t off = rd32(file + index_off + i * 8u + 4u);
        uint16_t w;
        uint16_t h;

        if (key < 32 || key > 126 || off + 12u > (uint32_t)fsz) {
            continue;
        }
        w = rd16(file + off + 8);
        h = rd16(file + off + 10);
        need_px += (size_t)w * (size_t)h;
    }
    /* Space shim. */
    need_px += (size_t)(word_shim > 0 ? word_shim : 1) * 1u;
    gb->px_store = (ta_pack66_t *)calloc(need_px, sizeof(ta_pack66_t));
    if (gb->px_store == NULL) {
        free(file);
        return -1;
    }
    gb->px_cap = need_px;
    gb->word_shim_w = (uint16_t)word_shim;
    gb->text_h = 0;
    ta_glyph_map_clear(&gb->map);

    for (i = 0; i < 95; i++) {
        gb->kern[i] = (int8_t)letter_shim;
    }
    gb->kern[0] = 0; /* after space / word gap: device sets this */

    /* Space: transparent word shim. */
    {
        uint16_t sw = gb->word_shim_w > 0 ? gb->word_shim_w : 1;
        ta_pack66_t *px = alloc_px(gb, (size_t)sw);
        ta_shape_bitmap_t *g = &gb->glyphs[0];

        if (px == NULL) {
            free(file);
            ta_glyph_bin_reset(gb);
            return -1;
        }
        memset(g, 0, sizeof(*g));
        g->tag = TA_SHAPE_TAG_BITMAP;
        g->w = sw;
        g->h = 1;
        g->pixels = px;
        if (ta_shape_table_set(1, g) != 0 ||
            ta_glyph_map_set(&gb->map, ' ', 1) != 0) {
            free(file);
            ta_glyph_bin_reset(gb);
            return -1;
        }
    }

    for (i = 0; i < count; i++) {
        uint32_t key = rd32(file + index_off + i * 8u);
        uint32_t off = rd32(file + index_off + i * 8u + 4u);
        uint16_t w;
        uint16_t h;
        const uint8_t *rgba;
        ta_pack66_t *px;
        ta_shape_bitmap_t *g;
        size_t k;
        unsigned gi;

        if (key < 33 || key > 126 || off + 12u > (uint32_t)fsz) {
            continue;
        }
        w = rd16(file + off + 8);
        h = rd16(file + off + 10);
        if ((size_t)off + 12u + (size_t)w * (size_t)h * 4u > (size_t)fsz) {
            continue;
        }
        rgba = file + off + 12;
        px = alloc_px(gb, (size_t)w * (size_t)h);
        if (px == NULL) {
            free(file);
            ta_glyph_bin_reset(gb);
            return -1;
        }
        for (k = 0; k < (size_t)w * (size_t)h; k++) {
            uint8_t a = rgba[k * 4u + 3u];
            uint8_t a2 = a2_of(a);

            /* a2==0 must be TRANSPARENT; white+a2==0 is additive wash. */
            if (a2 == 0u) {
                px[k] = TA_PACK66_TRANSPARENT;
            } else {
                px[k] = ta_pack66_rgba(0x3f, 0x3f, 0x3f, a2);
            }
        }
        gi = (unsigned)(key - 32u);
        g = &gb->glyphs[gi];
        memset(g, 0, sizeof(*g));
        g->tag = TA_SHAPE_TAG_BITMAP;
        g->w = w;
        g->h = h;
        g->pixels = px;
        if (h > gb->text_h) {
            gb->text_h = h;
        }
        if (ta_shape_table_set(1u + gi, g) != 0 ||
            ta_glyph_map_set(&gb->map, (char)key, 1u + gi) != 0) {
            free(file);
            ta_glyph_bin_reset(gb);
            return -1;
        }
    }
    if (gb->text_h == 0) {
        gb->text_h = (uint16_t)height;
    }
    free(file);
    gb->ready = 1;
    return 0;
}

int ta_base_from_rgba_file(ta_pack66_t *dst, uint16_t w, uint16_t h,
                           const char *path) {
    FILE *fp;
    size_t n;
    size_t k;
    uint8_t *rgba;

    if (dst == NULL || path == NULL || w == 0 || h == 0) {
        return -1;
    }
    n = (size_t)w * (size_t)h * 4u;
    rgba = (uint8_t *)malloc(n);
    if (rgba == NULL) {
        return -1;
    }
    fp = fopen(path, "rb");
    if (fp == NULL || fread(rgba, 1, n, fp) != n) {
        if (fp != NULL) {
            fclose(fp);
        }
        free(rgba);
        return -1;
    }
    fclose(fp);
    for (k = 0; k < (size_t)w * (size_t)h; k++) {
        const uint8_t *p = rgba + k * 4u;

        dst[k] = ta_pack66_rgba((uint8_t)(p[0] >> 2), (uint8_t)(p[1] >> 2),
                                (uint8_t)(p[2] >> 2), 3);
    }
    free(rgba);
    return 0;
}
