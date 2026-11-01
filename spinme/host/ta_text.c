#include "ta_text.h"

#include <string.h>

void ta_glyph_map_clear(ta_glyph_map_t *m) {
    if (m != NULL) {
        memset(m, 0, sizeof(*m));
    }
}

int ta_glyph_map_set(ta_glyph_map_t *m, char ch, unsigned shape_idx) {
    unsigned i;

    if (m == NULL || ch < 32 || ch > 126) {
        return -1;
    }
    i = (unsigned)(ch - 32);
    m->idx[i] = shape_idx;
    return 0;
}

int ta_text_build(ta_shape_l2r_t *out, const char *ascii,
                  const ta_glyph_map_t *glyphs, const int8_t *kern_table,
                  uint32_t *pack_buf, size_t pack_cap, int8_t *kern_buf,
                  size_t kern_cap) {
    unsigned idxs[128];
    size_t n = 0;
    size_t nw = 0;
    size_t i;
    int tag = TA_PACK_TAG_3x10;

    if (out == NULL || ascii == NULL || glyphs == NULL || pack_buf == NULL ||
        kern_buf == NULL) {
        return -1;
    }
    for (i = 0; ascii[i] != '\0'; i++) {
        unsigned gi;
        char ch = ascii[i];

        if (ch < 32 || ch > 126) {
            return -1;
        }
        gi = glyphs->idx[(unsigned)(ch - 32)];
        if (gi == 0 || ta_shape_table_get(gi) == NULL) {
            return -1;
        }
        if (n >= 128 || n >= kern_cap) {
            return -1;
        }
        idxs[n] = gi;
        if (kern_table != NULL) {
            kern_buf[n] = kern_table[(unsigned)(ch - 32)];
        } else {
            kern_buf[n] = 0;
        }
        n++;
    }
    /* Prefer denser pack when idxs fit. */
    {
        size_t j;
        int ok5 = 1;
        for (j = 0; j < n; j++) {
            if (idxs[j] > 31u) {
                ok5 = 0;
                break;
            }
        }
        if (ok5) {
            tag = TA_PACK_TAG_6x5;
        }
    }
    if (ta_shapepack_encode(pack_buf, pack_cap, &nw, idxs, n, tag) != 0) {
        return -1;
    }
    memset(out, 0, sizeof(*out));
    out->tag = TA_SHAPE_TAG_L2R;
    out->dirty = 1;
    out->pack = pack_buf;
    out->kernings = kern_buf;
    out->n_items = n;
    return ta_shape_l2r_compute_size(out);
}
