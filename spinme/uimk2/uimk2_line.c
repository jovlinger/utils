#include "uimk2_line.h"

#include <stddef.h>
#include <string.h>

const uimk2_glyph_entry *uimk2_glyph_find(uint32_t cp) {
    uint32_t want = cp;
    int pass;
    for (pass = 0; pass < 2; pass++) {
        uint32_t lo = 0, hi = uimk2_glyph_count;
        while (lo < hi) {
            uint32_t mid = lo + (hi - lo) / 2u;
            uint32_t c = uimk2_glyph_table[mid].codepoint;
            if (c == want) {
                return &uimk2_glyph_table[mid];
            }
            if (c < want) {
                lo = mid + 1u;
            } else {
                hi = mid;
            }
        }
        want = '?';
    }
    return NULL;
}

uint16_t uimk2_glyph_new(uimk2_bmtab *t, uint32_t cp) {
    const uimk2_glyph_entry *e = uimk2_glyph_find(cp);
    uint16_t g;
    if (e == NULL) {
        return 0;
    }
    g = uimk2_bm_new(t, UIMK2_BM_GLYPH);
    if (g == 0) {
        return 0;
    }
    t->bm[g].w = e->width;
    t->bm[g].h = uimk2_glyph_h;
    t->bm[g].u.glyph.alpha = &uimk2_glyph_alpha[e->offset];
    return g;
}

/* Decode one codepoint at *s and advance. An invalid or truncated sequence
 * consumes one byte and decodes as '?'. */
static uint32_t utf8_next(const unsigned char **s) {
    const unsigned char *p = *s;
    uint32_t cp;
    int n, k;
    if (p[0] < 0x80u) {
        *s = p + 1;
        return p[0];
    }
    if (p[0] >= 0xC2u && p[0] <= 0xDFu) {
        n = 1;
        cp = p[0] & 0x1Fu;
    } else if (p[0] >= 0xE0u && p[0] <= 0xEFu) {
        n = 2;
        cp = p[0] & 0x0Fu;
    } else if (p[0] >= 0xF0u && p[0] <= 0xF4u) {
        n = 3;
        cp = p[0] & 0x07u;
    } else {
        *s = p + 1;
        return '?';
    }
    for (k = 1; k <= n; k++) {
        if ((p[k] & 0xC0u) != 0x80u) {
            *s = p + 1;
            return '?';
        }
        cp = (cp << 6) | (p[k] & 0x3Fu);
    }
    *s = p + 1 + n;
    return cp;
}

static uint32_t align4(uint32_t n) { return (n + 3u) & ~3u; }

bool uimk2_line_build(uimk2_bmtab *t, uimk2_arena *a, uimk2_line *line,
                      const char *utf8, uint16_t hsep, uint8_t comb,
                      const uint8_t paper[4]) {
    const unsigned char *s;
    uint32_t n = 0, width = 0, idx_bytes, px_bytes, need;
    uint8_t *block;
    uint8_t *paper_px;
    uint16_t first, cache, paper_i, pack, k;
    uimk2_rect all;

    /* measure first, so a full arena or table changes nothing */
    for (s = (const unsigned char *)utf8; *s != 0;) {
        const uimk2_glyph_entry *e = uimk2_glyph_find(utf8_next(&s));
        if (e == NULL) {
            return false;
        }
        width += e->width;
        n++;
    }
    if (n > 1) {
        width += (n - 1u) * hsep;
    }
    /* cache + pack + glyphs, and a paper raster when the line has pixels */
    need = n + 2u + (width > 0u ? 1u : 0u);
    if (width > UINT16_MAX || need > (uint32_t)(t->cap - t->count)) {
        return false;
    }
    idx_bytes = align4((n + 1u) * (uint32_t)sizeof(uint16_t));
    px_bytes = width * (uint32_t)uimk2_glyph_h * 4u;
    block = (uint8_t *)uimk2_arena_alloc(a, idx_bytes + px_bytes + px_bytes);
    if (block == NULL) {
        return false;
    }

    first = t->count;
    cache = uimk2_bm_new(t, UIMK2_BM_CACHE);
    paper_i = 0;
    paper_px = block + idx_bytes;
    if (width > 0u) {
        uint32_t i;
        paper_i = uimk2_bm_new(t, UIMK2_BM_RGBA);
        t->bm[paper_i].w = (uint16_t)width;
        t->bm[paper_i].h = uimk2_glyph_h;
        t->bm[paper_i].u.rgba.px = paper_px;
        t->bm[paper_i].parent = cache;
        for (i = 0; i < width * (uint32_t)uimk2_glyph_h; i++) {
            memcpy(paper_px + i * 4u, paper, 4);
        }
    }
    pack = uimk2_bm_new(t, UIMK2_BM_L2R);
    line->idx = (uint16_t *)(void *)block;
    k = 0;
    for (s = (const unsigned char *)utf8; *s != 0;) {
        uint16_t g = uimk2_glyph_new(t, utf8_next(&s));
        t->bm[g].parent = pack;
        line->idx[k++] = g;
    }
    line->idx[k] = 0;

    t->bm[pack].parent = cache;
    t->bm[pack].combiner = comb;
    t->bm[pack].u.pack.items = line->idx;
    t->bm[pack].u.pack.sep = hsep;
    uimk2_bm_measure(t, pack);

    t->bm[cache].w = t->bm[pack].w;
    t->bm[cache].h = t->bm[pack].h;
    t->bm[cache].u.cache.bg = paper_i;
    t->bm[cache].u.cache.fg = pack;
    t->bm[cache].u.cache.px = paper_px + px_bytes;

    line->cache = cache;
    line->pack = pack;
    line->first_hdr = first;
    line->arena_off = uimk2_arena_off(a, block);
    line->arena_len = idx_bytes + px_bytes + px_bytes;

    all.x = 0;
    all.y = 0;
    all.w = t->bm[cache].w;
    all.h = t->bm[cache].h;
    uimk2_invalidate(t, cache, all, true);
    return true;
}
