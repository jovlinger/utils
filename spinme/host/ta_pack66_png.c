#include "ta_pack66_png.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

static uint8_t expand6(uint8_t v6) {
    return (uint8_t)((v6 * 255u) / 63u);
}

void ta_pack66_blit_fb(ta_pack66_t *fb, uint16_t panel_w, uint16_t panel_h,
                       int x, int y, int w, int h, const ta_pack66_t *src,
                       int stride_px) {
    int row;
    int col;

    if (fb == NULL || src == NULL || panel_w == 0 || panel_h == 0 || w <= 0 ||
        h <= 0 || stride_px <= 0) {
        return;
    }
    for (row = 0; row < h; row++) {
        int dy = y + row;

        if (dy < 0 || dy >= (int)panel_h) {
            continue;
        }
        for (col = 0; col < w; col++) {
            int dx = x + col;
            uint8_t r, g, b, a;
            ta_pack66_t p;

            if (dx < 0 || dx >= (int)panel_w) {
                continue;
            }
            p = src[(size_t)row * (size_t)stride_px + (size_t)col];
            ta_unpack66(p, &r, &g, &b, &a);
            if (a == 0) {
                continue;
            }
            fb[(size_t)dy * (size_t)panel_w + (size_t)dx] = p;
        }
    }
}

static void crc_table_init(uint32_t *table) {
    uint32_t n;
    uint32_t c;
    int k;

    for (n = 0; n < 256; n++) {
        c = n;
        for (k = 0; k < 8; k++) {
            if (c & 1u) {
                c = 0xedb88320u ^ (c >> 1);
            } else {
                c = c >> 1;
            }
        }
        table[n] = c;
    }
}

static uint32_t crc_update(uint32_t crc, const uint8_t *buf, size_t len,
                           const uint32_t *table) {
    size_t i;

    for (i = 0; i < len; i++) {
        crc = table[(crc ^ buf[i]) & 0xffu] ^ (crc >> 8);
    }
    return crc;
}

static uint32_t crc_chunk(const uint8_t *typeb, const uint8_t *data, size_t len,
                          const uint32_t *table) {
    uint32_t crc = 0xffffffffu;

    crc = crc_update(crc, typeb, 4, table);
    if (len > 0 && data != NULL) {
        crc = crc_update(crc, data, len, table);
    }
    return crc ^ 0xffffffffu;
}

static void be32(uint8_t *out, uint32_t v) {
    out[0] = (uint8_t)(v >> 24);
    out[1] = (uint8_t)(v >> 16);
    out[2] = (uint8_t)(v >> 8);
    out[3] = (uint8_t)v;
}

static int write_chunk(FILE *fp, const char *type, const uint8_t *data,
                       size_t len, const uint32_t *table) {
    uint8_t lenb[4];
    uint8_t typeb[4];
    uint8_t crcb[4];
    uint32_t crc;
    size_t i;

    be32(lenb, (uint32_t)len);
    for (i = 0; i < 4; i++) {
        typeb[i] = (uint8_t)type[i];
    }
    crc = crc_chunk(typeb, data, len, table);
    be32(crcb, crc);
    if (fwrite(lenb, 1, 4, fp) != 4 || fwrite(typeb, 1, 4, fp) != 4) {
        return -1;
    }
    if (len > 0 && fwrite(data, 1, len, fp) != len) {
        return -1;
    }
    if (fwrite(crcb, 1, 4, fp) != 4) {
        return -1;
    }
    return 0;
}

int ta_pack66_write_png(const char *path, uint16_t w, uint16_t h,
                        const ta_pack66_t *px) {
    FILE *fp;
    uint32_t table[256];
    uint8_t sig[8] = {137, 80, 78, 71, 13, 10, 26, 10};
    uint8_t ihdr[13];
    size_t raw_n;
    uint8_t *raw = NULL;
    uint8_t *comp = NULL;
    uLongf comp_bound;
    uLongf comp_n;
    size_t y;
    int rc = -1;

    if (path == NULL || px == NULL || w == 0 || h == 0) {
        return -1;
    }
    crc_table_init(table);
    raw_n = (size_t)h * ((size_t)w * 3u + 1u);
    raw = (uint8_t *)malloc(raw_n);
    if (raw == NULL) {
        return -1;
    }
    for (y = 0; y < h; y++) {
        size_t row = y * ((size_t)w * 3u + 1u);
        size_t x;

        raw[row] = 0; /* filter None */
        for (x = 0; x < w; x++) {
            uint8_t r6, g6, b6, a2;
            size_t o = row + 1u + x * 3u;

            ta_unpack66(px[y * w + x], &r6, &g6, &b6, &a2);
            if (a2 == 0) {
                raw[o] = 0;
                raw[o + 1] = 0;
                raw[o + 2] = 0;
            } else {
                raw[o] = expand6(r6);
                raw[o + 1] = expand6(g6);
                raw[o + 2] = expand6(b6);
            }
        }
    }
    comp_bound = compressBound((uLong)raw_n);
    comp = (uint8_t *)malloc(comp_bound);
    if (comp == NULL) {
        free(raw);
        return -1;
    }
    comp_n = comp_bound;
    if (compress2(comp, &comp_n, raw, (uLong)raw_n, Z_BEST_SPEED) != Z_OK) {
        free(comp);
        free(raw);
        return -1;
    }
    fp = fopen(path, "wb");
    if (fp == NULL) {
        free(comp);
        free(raw);
        return -1;
    }
    if (fwrite(sig, 1, 8, fp) != 8) {
        goto done;
    }
    be32(ihdr + 0, w);
    be32(ihdr + 4, h);
    ihdr[8] = 8;  /* bit depth */
    ihdr[9] = 2;  /* RGB */
    ihdr[10] = 0; /* compression */
    ihdr[11] = 0; /* filter */
    ihdr[12] = 0; /* interlace */
    if (write_chunk(fp, "IHDR", ihdr, 13, table) != 0) {
        goto done;
    }
    if (write_chunk(fp, "IDAT", comp, (size_t)comp_n, table) != 0) {
        goto done;
    }
    if (write_chunk(fp, "IEND", NULL, 0, table) != 0) {
        goto done;
    }
    rc = 0;
done:
    fclose(fp);
    free(comp);
    free(raw);
    return rc;
}
