#include "ta_shape_draw.h"

#include <stdlib.h>
#include <string.h>

/* Heap table: 1024 slots is too large for ESP32 DRAM BSS. */
static ta_sd_shape_t *g_tab;

static int ensure_tab(void) {
    if (g_tab != NULL) {
        return 0;
    }
    g_tab = (ta_sd_shape_t *)calloc(TA_SD_SLOTS, sizeof(ta_sd_shape_t));
    return g_tab == NULL ? -1 : 0;
}

void ta_sd_reset(void) {
    unsigned i;

    if (g_tab == NULL) {
        (void)ensure_tab();
        return;
    }
    for (i = 0; i < TA_SD_SLOTS; i++) {
        free(g_tab[i].pixels);
        memset(&g_tab[i], 0, sizeof(g_tab[i]));
        g_tab[i].tag = TA_SD_TAG_NONE;
    }
}

ta_sd_shape_t *ta_sd_get(unsigned idx) {
    if (ensure_tab() != 0 || idx >= TA_SD_SLOTS) {
        return NULL;
    }
    return &g_tab[idx];
}

uint32_t ta_sd_pack3(unsigned a, unsigned b, unsigned c) {
    return (3u << 30) | ((a & TA_SD_REF_MASK) << 20) |
           ((b & TA_SD_REF_MASK) << 10) | (c & TA_SD_REF_MASK);
}

void ta_sd_unpack3(uint32_t word, unsigned *a, unsigned *b, unsigned *c) {
    if (a) {
        *a = (word >> 20) & TA_SD_REF_MASK;
    }
    if (b) {
        *b = (word >> 10) & TA_SD_REF_MASK;
    }
    if (c) {
        *c = word & TA_SD_REF_MASK;
    }
}

static size_t px_words(uint8_t tag, uint16_t w, uint16_t h) {
    size_t n = (size_t)w * (size_t)h;
    if (tag == TA_SD_TAG_XY) {
        n += (size_t)h * (size_t)TA_SD_RLC_N;
    }
    return n;
}

int ta_sd_alloc_bitmap(unsigned idx, uint8_t tag, uint16_t w, uint16_t h) {
    ta_sd_shape_t *s;
    size_t n;
    ta_pack66_t *px;

    if (ensure_tab() != 0 || idx == TA_SD_NONE || idx >= TA_SD_SLOTS ||
        w == 0 || h == 0) {
        return -1;
    }
    if (tag != TA_SD_TAG_BITMAP && tag != TA_SD_TAG_XY &&
        tag != TA_SD_TAG_COMPOSITE) {
        return -1;
    }
    s = &g_tab[idx];
    n = px_words(tag, w, h);
    px = (ta_pack66_t *)calloc(n, sizeof(ta_pack66_t));
    if (px == NULL) {
        return -1;
    }
    free(s->pixels);
    memset(s, 0, sizeof(*s));
    s->tag = tag;
    s->w = w;
    s->h = h;
    s->pixels = px;
    s->dirty = 1;
    return 0;
}

void ta_sd_free(unsigned idx) {
    ta_sd_shape_t *s;

    if (g_tab == NULL || idx == TA_SD_NONE || idx >= TA_SD_SLOTS) {
        return;
    }
    s = &g_tab[idx];
    free(s->pixels);
    memset(s, 0, sizeof(*s));
    s->tag = TA_SD_TAG_NONE;
}

void ta_sd_rlc_clear_row(ta_sd_rlc_word_t *row_words) {
    int i;

    if (row_words == NULL) {
        return;
    }
    for (i = 0; i < TA_SD_RLC_N; i++) {
        row_words[i] = 0;
    }
}

static void encode_pair(uint8_t *bytes, uint8_t off_u, uint8_t len_u) {
    bytes[0] = off_u;
    bytes[1] = len_u;
}

int ta_sd_rlc_set_ranges(ta_sd_rlc_word_t *row_words, const uint8_t *off_u,
                         const uint8_t *len_u, int n_in) {
    uint8_t bytes[8];
    int i;

    if (row_words == NULL || n_in < 0 || n_in > 4) {
        return -1;
    }
    memset(bytes, 0, sizeof(bytes));
    for (i = 0; i < n_in; i++) {
        encode_pair(bytes + (size_t)i * 2u, off_u[i], len_u[i]);
    }
    memcpy(row_words, bytes, 4);
    memcpy(row_words + 1, bytes + 4, 4);
    return 0;
}

int ta_sd_rlc_merge_to_n(uint8_t *off_u, uint8_t *len_u, int n_in, int max_out) {
    int n = n_in;

    if (off_u == NULL || len_u == NULL || n_in < 0 || max_out < 1) {
        return -1;
    }
    /* Drop null lens; assume sorted by off. */
    {
        int w = 0;
        int i;
        for (i = 0; i < n; i++) {
            if (len_u[i] == 0) {
                continue;
            }
            off_u[w] = off_u[i];
            len_u[w] = len_u[i];
            w++;
        }
        n = w;
    }
    while (n > max_out) {
        int best = 0;
        int best_gap = 1000;
        int i;
        for (i = 0; i < n - 1; i++) {
            int end = (int)off_u[i] + (int)len_u[i];
            int gap = (int)off_u[i + 1] - end;
            if (gap < best_gap) {
                best_gap = gap;
                best = i;
            }
        }
        /* Merge best with best+1. */
        {
            int end0 = (int)off_u[best] + (int)len_u[best];
            int end1 = (int)off_u[best + 1] + (int)len_u[best + 1];
            int new_end = end1 > end0 ? end1 : end0;
            len_u[best] = (uint8_t)(new_end - (int)off_u[best]);
            {
                int j;
                for (j = best + 1; j < n - 1; j++) {
                    off_u[j] = off_u[j + 1];
                    len_u[j] = len_u[j + 1];
                }
            }
            n--;
        }
    }
    return n;
}

ta_sd_rlc_word_t *ta_sd_xy_rlc(ta_sd_shape_t *xy) {
    if (xy == NULL || xy->tag != TA_SD_TAG_XY || xy->pixels == NULL) {
        return NULL;
    }
    return (ta_sd_rlc_word_t *)(xy->pixels + (size_t)xy->w * (size_t)xy->h);
}

static uint8_t clamp6(unsigned v) {
    return (uint8_t)(v > 63u ? 63u : v);
}

ta_pack66_t ta_sd_word(uint8_t r6, uint8_t g6, uint8_t b6, uint8_t a2) {
    return ((ta_pack66_t)(r6 & 0x3f)) | ((ta_pack66_t)(g6 & 0x3f) << 8) |
           ((ta_pack66_t)(b6 & 0x3f) << 16) |
           ((ta_pack66_t)(a2 & 3u) << TA_PACK66_A2_SHIFT);
}

static void raw_rgb(ta_pack66_t px, uint8_t *r, uint8_t *g, uint8_t *b) {
    *r = (uint8_t)(px & 0x3fu);
    *g = (uint8_t)((px >> 8) & 0x3fu);
    *b = (uint8_t)((px >> 16) & 0x3fu);
}

ta_pack66_t ta_sd_blend(ta_pack66_t dst, ta_pack66_t src) {
    uint8_t sr, sg, sb, sa;
    uint8_t dr, dg, db;
    unsigned inv;

    if (src == TA_PACK66_TRANSPARENT) {
        return dst;
    }
    sa = (uint8_t)((src >> TA_PACK66_A2_SHIFT) & 3u);
    raw_rgb(src, &sr, &sg, &sb);
    raw_rgb(dst, &dr, &dg, &db);
    /* a2==0 and nonzero word: clamped additive (design). */
    if (sa == 0) {
        return ta_sd_word(clamp6((unsigned)dr + (unsigned)sr),
                          clamp6((unsigned)dg + (unsigned)sg),
                          clamp6((unsigned)db + (unsigned)sb), 3);
    }
    if (sa >= 3) {
        return src;
    }
    inv = 3u - (unsigned)sa;
    return ta_sd_word((uint8_t)(((unsigned)sr * sa + (unsigned)dr * inv) / 3u),
                      (uint8_t)(((unsigned)sg * sa + (unsigned)dg * inv) / 3u),
                      (uint8_t)(((unsigned)sb * sa + (unsigned)db * inv) / 3u),
                      3);
}

void ta_sd_blit(ta_pack66_t *dst, uint16_t dw, uint16_t dh, int ox, int oy,
                const ta_pack66_t *src, uint16_t sw, uint16_t sh) {
    uint16_t y;
    uint16_t x;

    if (dst == NULL || src == NULL) {
        return;
    }
    for (y = 0; y < sh; y++) {
        int dy = oy + (int)y;
        if (dy < 0 || dy >= (int)dh) {
            continue;
        }
        for (x = 0; x < sw; x++) {
            int dx = ox + (int)x;
            size_t di;
            ta_pack66_t px;

            if (dx < 0 || dx >= (int)dw) {
                continue;
            }
            px = src[(size_t)y * sw + x];
            di = (size_t)dy * dw + (size_t)dx;
            dst[di] = ta_sd_blend(dst[di], px);
        }
    }
}

static void decode_rlc_row(const ta_sd_rlc_word_t *row_words, uint8_t *off_u,
                           uint8_t *len_u, int *n_out) {
    uint8_t bytes[8];
    int i;
    int n = 0;

    memcpy(bytes, row_words, 4);
    memcpy(bytes + 4, row_words + 1, 4);
    for (i = 0; i < 4; i++) {
        uint8_t ou = bytes[(size_t)i * 2u];
        uint8_t lu = bytes[(size_t)i * 2u + 1u];
        if (lu == 0) {
            continue;
        }
        off_u[n] = ou;
        len_u[n] = lu;
        n++;
    }
    *n_out = n;
}

void ta_sd_xy_mark_full_dirty(ta_sd_shape_t *xy) {
    ta_sd_rlc_word_t *rlc;
    uint16_t y;
    uint8_t off[1];
    uint8_t len[1];
    unsigned lu;

    if (xy == NULL || xy->tag != TA_SD_TAG_XY) {
        return;
    }
    rlc = ta_sd_xy_rlc(xy);
    if (rlc == NULL) {
        return;
    }
    off[0] = 0;
    lu = ((unsigned)xy->w + 1u) / 2u;
    if (lu > 255u) {
        lu = 255u;
    }
    if (lu == 0u) {
        lu = 1u;
    }
    len[0] = (uint8_t)lu;
    for (y = 0; y < xy->h; y++) {
        ta_sd_rlc_set_ranges(rlc + (size_t)y * TA_SD_RLC_N, off, len, 1);
    }
}

int ta_sd_xy_rebuild_from_child(unsigned xy_idx) {
    ta_sd_shape_t *xy;
    ta_sd_shape_t *ch;
    size_t n;

    xy = ta_sd_get(xy_idx);
    if (xy == NULL || xy->tag != TA_SD_TAG_XY || xy->pixels == NULL) {
        return -1;
    }
    ch = ta_sd_get(xy->u.xy.child);
    if (ch == NULL || ch->tag != TA_SD_TAG_BITMAP || ch->pixels == NULL) {
        return -1;
    }
    n = (size_t)xy->w * (size_t)xy->h;
    memset(xy->pixels, 0, n * sizeof(ta_pack66_t));
    ta_sd_blit(xy->pixels, xy->w, xy->h, 0, 0, ch->pixels, ch->w, ch->h);
    xy->dirty = 1;
    return 0;
}

void ta_sd_xy_blit_glass(ta_pack66_t *glass, uint16_t gw, uint16_t gh,
                         unsigned xy_idx) {
    ta_sd_shape_t *xy;
    ta_sd_rlc_word_t *rlc;
    uint16_t y;

    xy = ta_sd_get(xy_idx);
    if (glass == NULL || xy == NULL || xy->tag != TA_SD_TAG_XY ||
        xy->pixels == NULL) {
        return;
    }
    rlc = ta_sd_xy_rlc(xy);
    if (rlc == NULL) {
        return;
    }
    for (y = 0; y < xy->h; y++) {
        uint8_t off_u[4];
        uint8_t len_u[4];
        int nr = 0;
        int i;

        decode_rlc_row(rlc + (size_t)y * TA_SD_RLC_N, off_u, len_u, &nr);
        for (i = 0; i < nr; i++) {
            unsigned px0 = (unsigned)off_u[i] * 2u;
            unsigned pxn = px0 + (unsigned)len_u[i] * 2u;
            unsigned x;

            if (pxn > xy->w) {
                pxn = xy->w;
            }
            for (x = px0; x < pxn; x++) {
                int dx = (int)xy->u.xy.x + (int)x;
                int dy = (int)xy->u.xy.y + (int)y;
                size_t di;
                ta_pack66_t src;

                if (dx < 0 || dy < 0 || dx >= (int)gw || dy >= (int)gh) {
                    continue;
                }
                di = (size_t)dy * gw + (size_t)dx;
                src = xy->pixels[(size_t)y * xy->w + x];
                glass[di] = ta_sd_blend(glass[di], src);
            }
        }
    }
}

void ta_sd_glass_paint_xys(ta_pack66_t *glass, uint16_t gw, uint16_t gh,
                           const unsigned *xy_idxs, size_t n) {
    size_t i;

    if (glass == NULL || xy_idxs == NULL) {
        return;
    }
    for (i = 0; i < n; i++) {
        ta_sd_xy_blit_glass(glass, gw, gh, xy_idxs[i]);
    }
}

int ta_sd_xy_push_dirty(unsigned xy_idx, ta_sd_push_rect_fn push, void *ctx) {
    ta_sd_shape_t *xy;
    ta_sd_rlc_word_t *rlc;
    uint16_t y;
    int spans = 0;

    if (push == NULL) {
        return -1;
    }
    xy = ta_sd_get(xy_idx);
    if (xy == NULL || xy->tag != TA_SD_TAG_XY || xy->pixels == NULL) {
        return -1;
    }
    rlc = ta_sd_xy_rlc(xy);
    if (rlc == NULL) {
        return -1;
    }
    /* One push per RLC range per raster (no coalesce). */
    for (y = 0; y < xy->h; y++) {
        uint8_t off_u[4];
        uint8_t len_u[4];
        int nr = 0;
        int i;

        decode_rlc_row(rlc + (size_t)y * TA_SD_RLC_N, off_u, len_u, &nr);
        for (i = 0; i < nr; i++) {
            unsigned px0 = (unsigned)off_u[i] * 2u;
            unsigned pxn = px0 + (unsigned)len_u[i] * 2u;
            int w;

            if (pxn > xy->w) {
                pxn = xy->w;
            }
            w = (int)pxn - (int)px0;
            if (w <= 0) {
                continue;
            }
            push((int)xy->u.xy.x + (int)px0, (int)xy->u.xy.y + (int)y, w, 1,
                 xy->pixels + (size_t)y * xy->w + px0, (int)xy->w, ctx);
            spans++;
        }
    }
    return spans;
}

void ta_sd_xy_derive_rlc(ta_sd_shape_t *xy, const ta_pack66_t *old_px,
                         const ta_pack66_t *new_px) {
    ta_sd_rlc_word_t *rlc;
    uint16_t y;

    if (xy == NULL || xy->tag != TA_SD_TAG_XY || old_px == NULL ||
        new_px == NULL) {
        return;
    }
    rlc = ta_sd_xy_rlc(xy);
    if (rlc == NULL) {
        return;
    }
    for (y = 0; y < xy->h; y++) {
        uint8_t off[64];
        uint8_t len[64];
        int n = 0;
        uint16_t x = 0;
        const ta_pack66_t *orow = old_px + (size_t)y * xy->w;
        const ta_pack66_t *nrow = new_px + (size_t)y * xy->w;

        while (x < xy->w) {
            if (orow[x] == nrow[x]) {
                x++;
                continue;
            }
            {
                uint16_t start = x;
                while (x < xy->w && orow[x] != nrow[x]) {
                    x++;
                }
                if (n < 64) {
                    /* store /2 units; clamp to 255 */
                    unsigned ou = start / 2u;
                    unsigned lu = (x - start) / 2u;
                    if (lu == 0) {
                        lu = 1;
                    }
                    if (ou > 255u) {
                        ou = 255u;
                    }
                    if (lu > 255u) {
                        lu = 255u;
                    }
                    off[n] = (uint8_t)ou;
                    len[n] = (uint8_t)lu;
                    n++;
                }
            }
        }
        n = ta_sd_rlc_merge_to_n(off, len, n, 4);
        if (n < 0) {
            n = 0;
        }
        ta_sd_rlc_set_ranges(rlc + (size_t)y * TA_SD_RLC_N, off, len, n);
    }
}

static void mark_reachable(unsigned idx, uint8_t *mark) {
    ta_sd_shape_t *s;
    unsigned a, b, c;

    if (idx == TA_SD_NONE || idx >= TA_SD_SLOTS || mark[idx]) {
        return;
    }
    mark[idx] = 1;
    s = &g_tab[idx];
    if (s->tag == TA_SD_TAG_COMPOSITE) {
        ta_sd_unpack3(s->u.composite.refs, &a, &b, &c);
        mark_reachable(a, mark);
        mark_reachable(b, mark);
        mark_reachable(c, mark);
    } else if (s->tag == TA_SD_TAG_XY) {
        mark_reachable(s->u.xy.child, mark);
    }
}

int ta_sd_gc(unsigned root) {
    uint8_t mark[TA_SD_SLOTS];
    unsigned remap[TA_SD_SLOTS];
    unsigned i;
    unsigned dst;
    unsigned new_root;

    if (ensure_tab() != 0) {
        return -1;
    }
    memset(mark, 0, sizeof(mark));
    for (i = 0; i < TA_SD_SLOTS; i++) {
        remap[i] = i;
    }
    /* Locked assets always live. */
    for (i = 1; i <= TA_SD_LOCKED_MAX && i < TA_SD_SLOTS; i++) {
        if (g_tab[i].tag != TA_SD_TAG_NONE) {
            mark[i] = 1;
        }
    }
    mark_reachable(root, mark);

    /* Free unmarked above locked region. */
    for (i = TA_SD_LOCKED_MAX + 1; i < TA_SD_SLOTS; i++) {
        if (!mark[i] && g_tab[i].tag != TA_SD_TAG_NONE) {
            ta_sd_free(i);
        }
    }

    /* Compact into region above locked; build remap. */
    dst = TA_SD_LOCKED_MAX + 1;
    for (i = TA_SD_LOCKED_MAX + 1; i < TA_SD_SLOTS; i++) {
        if (g_tab[i].tag == TA_SD_TAG_NONE) {
            continue;
        }
        if (i != dst) {
            g_tab[dst] = g_tab[i];
            memset(&g_tab[i], 0, sizeof(g_tab[i]));
            g_tab[i].tag = TA_SD_TAG_NONE;
        }
        remap[i] = dst;
        dst++;
    }

    /* Rewrite child refs for survivors above locked. */
    for (i = TA_SD_LOCKED_MAX + 1; i < TA_SD_SLOTS; i++) {
        ta_sd_shape_t *s = &g_tab[i];
        unsigned x, y, z;

        if (s->tag == TA_SD_TAG_COMPOSITE) {
            ta_sd_unpack3(s->u.composite.refs, &x, &y, &z);
            s->u.composite.refs =
                ta_sd_pack3(remap[x], remap[y], remap[z]);
        } else if (s->tag == TA_SD_TAG_XY) {
            s->u.xy.child = (uint16_t)remap[s->u.xy.child];
        }
    }
    new_root = remap[root];
    (void)new_root;
    return 0;
}
