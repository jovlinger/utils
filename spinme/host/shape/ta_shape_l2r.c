#include "ta_shape_l2r.h"

#include <string.h>

static int bits_per_idx(int tag) {
    switch (tag) {
    case TA_PACK_TAG_3x10:
        return 10;
    case TA_PACK_TAG_4x7:
        return 7;
    case TA_PACK_TAG_5x6:
        return 6;
    case TA_PACK_TAG_6x5:
        return 5;
    default:
        return -1;
    }
}

static int idxs_per_word(int tag) {
    switch (tag) {
    case TA_PACK_TAG_3x10:
        return 3;
    case TA_PACK_TAG_4x7:
        return 4;
    case TA_PACK_TAG_5x6:
        return 5;
    case TA_PACK_TAG_6x5:
        return 6;
    default:
        return -1;
    }
}

int ta_shapepack_encode(uint32_t *out, size_t out_cap, size_t *out_n,
                        const unsigned *idxs, size_t n, int tag) {
    int bpi;
    int ipw;
    size_t i;
    size_t wcount = 0;

    bpi = bits_per_idx(tag);
    ipw = idxs_per_word(tag);
    if (bpi < 0 || out == NULL || out_n == NULL || (n > 0 && idxs == NULL)) {
        return -1;
    }
    i = 0;
    while (i < n) {
        uint32_t word = ((uint32_t)tag & 3u) << 30;
        int slot;

        if (wcount >= out_cap) {
            return -1;
        }
        for (slot = 0; slot < ipw && i < n; slot++, i++) {
            unsigned mask = (1u << (unsigned)bpi) - 1u;
            if (idxs[i] > mask) {
                return -1;
            }
            word |= ((uint32_t)(idxs[i] & mask)) << (unsigned)(slot * bpi);
        }
        out[wcount++] = word;
    }
    /* Terminator: tag word with all idxs zero. */
    if (wcount >= out_cap) {
        return -1;
    }
    out[wcount++] = ((uint32_t)tag & 3u) << 30;
    *out_n = wcount;
    return 0;
}

size_t ta_shapepack_decode_word(uint32_t word, unsigned *idxs, size_t max) {
    int tag = (int)((word >> 30) & 3u);
    int bpi = bits_per_idx(tag);
    int ipw = idxs_per_word(tag);
    size_t n = 0;
    int slot;
    int any = 0;

    if (bpi < 0 || idxs == NULL) {
        return 0;
    }
    for (slot = 0; slot < ipw && n < max; slot++) {
        unsigned mask = (1u << (unsigned)bpi) - 1u;
        unsigned v = (unsigned)((word >> (unsigned)(slot * bpi)) & mask);
        if (v != 0) {
            any = 1;
        }
        idxs[n++] = v;
    }
    if (!any) {
        return 0; /* terminator / empty */
    }
    return n;
}

int ta_shape_l2r_compute_size(ta_shape_l2r_t *l2r) {
    size_t i;
    size_t wi;
    unsigned tmp[8];
    int wsum = 0;
    int hmax = 0;
    size_t item = 0;

    if (l2r == NULL || l2r->pack == NULL) {
        return -1;
    }
    wi = 0;
    for (;;) {
        size_t got = ta_shapepack_decode_word(l2r->pack[wi], tmp, 8);
        if (got == 0) {
            break;
        }
        for (i = 0; i < got; i++) {
            ta_shape_bitmap_t *ch;
            int kern = 0;

            if (tmp[i] == 0) {
                continue;
            }
            ch = ta_shape_table_get(tmp[i]);
            if (ch == NULL) {
                return -1;
            }
            wsum += (int)ch->w;
            if ((int)ch->h > hmax) {
                hmax = (int)ch->h;
            }
            if (l2r->kernings != NULL && item < l2r->n_items) {
                kern = (int)l2r->kernings[item];
            }
            wsum += kern;
            item++;
        }
        wi++;
    }
    l2r->w = (uint16_t)(wsum < 0 ? 0 : wsum);
    l2r->h = (uint16_t)hmax;
    return 0;
}
