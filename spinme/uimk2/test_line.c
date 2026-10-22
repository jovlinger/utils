/* Host tests for Glyph nodes on the flash font table and for text lines.
 * Linked against the generated Helvetica 12 px table (build/glyphs_12.c). */
#include "uimk2_line.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int failures;
static int checks;

#define CHECK(cond)                                                        \
    do {                                                                   \
        checks++;                                                          \
        if (!(cond)) {                                                     \
            failures++;                                                    \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__,         \
                    __LINE__, #cond);                                      \
        }                                                                  \
    } while (0)

#define CAP 64
#define SW 64
#define SH 20
#define ARENA_BYTES 8192

static uimk2_bm storage[CAP];
static uint8_t screen[SW * SH * 4];
static uint32_t arena_buf[ARENA_BYTES / 4];

static const uint8_t CLEAR[4] = {0, 0, 0, 0};
static const uint8_t BLACK[4] = {0, 0, 0, 255};

#define INK_COMB 1
static const uimk2_combiner COMBS[] = {
    {0, UIMK2_COMB_SET, {0, 0, 0, 0}},                 /* 0: none */
    {UIMK2_COMB_RGB, UIMK2_COMB_SET, {200, 100, 50, 0}}, /* ink color */
    {UIMK2_COMB_R, UIMK2_COMB_SET, {0, 0, 0, 0}},      /* zero red */
};

static uint32_t align4(uint32_t n) { return (n + 3u) & ~3u; }

static int px_eq(const uint8_t *p, int r, int g, int b, int a) {
    return p[0] == r && p[1] == g && p[2] == b && p[3] == a;
}

static int near(int got, int want) { return got - want <= 1 && want - got <= 1; }

static uint16_t make_root(uimk2_bmtab *t, uimk2_layout_item *items,
                          uint16_t n, const uint8_t paper[4]) {
    uint16_t root;
    uimk2_bmtab_init(t, storage, CAP);
    uimk2_bmtab_set_combiners(t, COMBS,
                              (uint16_t)(sizeof COMBS / sizeof COMBS[0]));
    memset(screen, 0xEE, sizeof screen);
    root = uimk2_bm_new(t, UIMK2_BM_LAYOUT);
    t->root = root;
    t->bm[root].w = SW;
    t->bm[root].h = SH;
    t->bm[root].u.layout.items = items;
    t->bm[root].u.layout.n = n;
    t->bm[root].u.layout.px = screen;
    memcpy(t->bm[root].u.layout.paper, paper, 4);
    return root;
}

static void full_damage(uimk2_bmtab *t, uint16_t idx) {
    uimk2_rect r;
    r.x = 0;
    r.y = 0;
    r.w = t->bm[idx].w;
    r.h = t->bm[idx].h;
    uimk2_invalidate(t, idx, r, true);
}

static void test_table_shape(void) {
    uint16_t i, f;
    uint32_t off = 0;
    int alpha_ok = 1;
    CHECK(uimk2_glyph_count > 0);
    CHECK(uimk2_glyph_b > 0 && uimk2_glyph_b < uimk2_glyph_h);
    for (i = 0; i < uimk2_glyph_count; i++) {
        const uimk2_glyph_entry *e = &uimk2_glyph_table[i];
        uint32_t k;
        if (i > 0) {
            CHECK(e->codepoint > uimk2_glyph_table[i - 1].codepoint);
        }
        CHECK(e->offset == off);
        for (k = 0; k < (uint32_t)e->width * uimk2_glyph_h; k++) {
            uint8_t v = uimk2_glyph_alpha[e->offset + k];
            int hit = 0;
            for (f = 0; f <= 64; f++) {
                if (v == f * 255 / 64) {
                    hit = 1;
                }
            }
            alpha_ok = alpha_ok && hit;
        }
        off += (uint32_t)e->width * uimk2_glyph_h;
    }
    /* every alpha byte is filled * 255 / 64 for some filled in 0..64 */
    CHECK(alpha_ok);
}

static void test_glyph_find(void) {
    const uimk2_glyph_entry *q = uimk2_glyph_find('?');
    CHECK(q != NULL && q->codepoint == '?');
    CHECK(uimk2_glyph_find('A')->codepoint == 'A');
    CHECK(uimk2_glyph_find(' ')->codepoint == ' ');
    CHECK(uimk2_glyph_find('~')->codepoint == '~');
    CHECK(uimk2_glyph_find(0xE9u) == q);
    CHECK(uimk2_glyph_find(0x01u) == q);
    CHECK(uimk2_glyph_find(0x1F600u) == q);
}

/* A Glyph node points at the flash alpha, is H tall, and samples as white
 * with alpha equal to the stored coverage. */
static void test_glyph_reads_flash(void) {
    uimk2_bmtab t;
    uimk2_layout_item items[1];
    const uimk2_glyph_entry *e = uimk2_glyph_find('g');
    uint16_t root, g, before;
    uint32_t x, y;
    int ok = 1;
    root = make_root(&t, items, 1, CLEAR);
    before = t.count;
    g = uimk2_glyph_new(&t, 'g');
    CHECK(g != 0 && t.count == before + 1);
    CHECK(t.bm[g].kind == UIMK2_BM_GLYPH);
    CHECK(t.bm[g].w == e->width);
    CHECK(t.bm[g].h == uimk2_glyph_h);
    CHECK(t.bm[g].u.glyph.alpha == &uimk2_glyph_alpha[e->offset]);

    items[0].x = 5;
    items[0].y = 2;
    items[0].idx = g;
    t.bm[g].parent = root;
    full_damage(&t, root);
    uimk2_repaint(&t);
    for (y = 0; y < uimk2_glyph_h; y++) {
        for (x = 0; x < e->width; x++) {
            uint8_t a = uimk2_glyph_alpha[e->offset + y * e->width + x];
            const uint8_t *p = &screen[((y + 2) * SW + x + 5) * 4];
            if (a == 0) {
                ok = ok && px_eq(p, 0, 0, 0, 0);
            } else {
                ok = ok && px_eq(p, 255, 255, 255, a);
            }
        }
    }
    CHECK(ok);

    /* missing codepoint: the '?' glyph */
    g = uimk2_glyph_new(&t, 0xE9u);
    CHECK(t.bm[g].u.glyph.alpha ==
          &uimk2_glyph_alpha[uimk2_glyph_find('?')->offset]);
}

static void test_combiner_set(void) {
    uimk2_bmtab t;
    uint8_t s[4] = {255, 255, 255, 77};
    uimk2_bmtab_init(&t, storage, CAP);
    uimk2_bmtab_set_combiners(&t, COMBS,
                              (uint16_t)(sizeof COMBS / sizeof COMBS[0]));
    uimk2_combine(&t, INK_COMB, s);
    CHECK(px_eq(s, 200, 100, 50, 77)); /* SET RGB leaves alpha */
    s[0] = 11;
    s[1] = 22;
    s[2] = 33;
    s[3] = 44;
    uimk2_combine(&t, 2, s);
    CHECK(px_eq(s, 0, 22, 33, 44)); /* SET R to 0 leaves G, B, A */
    uimk2_combine(&t, 0, s);
    CHECK(px_eq(s, 0, 22, 33, 44)); /* index 0 is none */
    uimk2_combine(&t, 9, s);
    CHECK(px_eq(s, 0, 22, 33, 44)); /* out of table is none */
}

/* A line takes one arena block (IdxList + cache), one Glyph header per
 * codepoint, and is tinted to the ink color over its paper. */
static void test_line_build_and_tint(void) {
    uimk2_bmtab t;
    uimk2_arena a;
    uimk2_line line;
    uimk2_layout_item items[1];
    const char *text = "Hi g";
    const uint16_t hsep = 1;
    uint16_t root, k, x, y, before;
    uint32_t top0, want_w = 0, cx = 0;
    int ok_parent = 1, ok_flash = 1, ok_px = 1, ok_root = 1;

    root = make_root(&t, items, 1, CLEAR);
    uimk2_arena_init(&a, arena_buf, sizeof arena_buf);
    top0 = a.top;
    before = t.count;
    CHECK(uimk2_line_build(&t, &a, &line, text, hsep, INK_COMB, BLACK));

    for (k = 0; text[k] != 0; k++) {
        want_w += uimk2_glyph_find((unsigned char)text[k])->width;
    }
    want_w += 3u * hsep;

    CHECK(t.count == before + 2 + 4);
    CHECK(line.first_hdr == before);
    CHECK(t.bm[line.cache].kind == UIMK2_BM_RGBA);
    CHECK(t.bm[line.pack].kind == UIMK2_BM_L2R);
    CHECK(t.bm[line.cache].u.rgba.child == line.pack);
    CHECK(t.bm[line.pack].parent == line.cache);
    CHECK(t.bm[line.cache].parent == 0);
    CHECK(t.bm[line.pack].combiner == INK_COMB);
    CHECK(t.bm[line.cache].w == want_w);
    CHECK(t.bm[line.cache].h == uimk2_glyph_h);
    CHECK(t.bm[line.cache].dirty && t.bm[line.cache].geom_dirty);

    /* the only arena bytes: the IdxList and the cache, one block */
    CHECK(line.arena_off == top0);
    CHECK(line.arena_len == align4(5u * 2u) + want_w * uimk2_glyph_h * 4u);
    CHECK(a.top - top0 == line.arena_len);
    CHECK(line.idx[4] == 0);
    for (k = 0; k < 4; k++) {
        const uimk2_bm *g = &t.bm[line.idx[k]];
        const uimk2_glyph_entry *e = uimk2_glyph_find((unsigned char)text[k]);
        ok_parent = ok_parent && g->kind == UIMK2_BM_GLYPH &&
                    g->parent == line.pack && g->h == uimk2_glyph_h;
        ok_flash = ok_flash && g->u.glyph.alpha == &uimk2_glyph_alpha[e->offset];
    }
    CHECK(ok_parent);
    CHECK(ok_flash);

    items[0].x = 3;
    items[0].y = 4;
    items[0].idx = line.cache;
    t.bm[line.cache].parent = root;
    full_damage(&t, line.cache);
    uimk2_repaint(&t);

    /* cache pixels: ink over paper by coverage; seps are paper */
    for (k = 0; k < 4; k++) {
        const uimk2_glyph_entry *e = uimk2_glyph_find((unsigned char)text[k]);
        for (y = 0; y < uimk2_glyph_h; y++) {
            for (x = 0; x < e->width; x++) {
                int al = uimk2_glyph_alpha[e->offset + y * e->width + x];
                const uint8_t *p =
                    &t.bm[line.cache].u.rgba.px[(y * want_w + cx + x) * 4u];
                ok_px = ok_px && near(p[0], 200 * al / 255) &&
                        near(p[1], 100 * al / 255) &&
                        near(p[2], 50 * al / 255) && p[3] == 255;
                if (al == 255) {
                    ok_px = ok_px && px_eq(p, 200, 100, 50, 255);
                }
                if (al == 0) {
                    ok_px = ok_px && px_eq(p, 0, 0, 0, 255);
                }
            }
            if (k < 3) {
                const uint8_t *p =
                    &t.bm[line.cache].u.rgba.px[(y * want_w + cx + e->width) * 4u];
                ok_px = ok_px && px_eq(p, 0, 0, 0, 255);
            }
        }
        cx += e->width + hsep;
    }
    CHECK(ok_px);
    /* 'H' has a fully covered pixel, so the ink color shows exactly */
    {
        const uimk2_glyph_entry *e = uimk2_glyph_find('H');
        int full = 0;
        uint32_t i;
        for (i = 0; i < (uint32_t)e->width * uimk2_glyph_h; i++) {
            full = full || uimk2_glyph_alpha[e->offset + i] == 255;
        }
        CHECK(full);
    }

    /* the root shows the opaque cache verbatim */
    for (y = 0; y < uimk2_glyph_h; y++) {
        for (x = 0; x < want_w; x++) {
            ok_root = ok_root &&
                      memcmp(&screen[((y + 4) * SW + x + 3) * 4],
                             &t.bm[line.cache].u.rgba.px[(y * want_w + x) * 4u],
                             4) == 0;
        }
    }
    CHECK(ok_root);
}

static void test_line_utf8(void) {
    uimk2_bmtab t;
    uimk2_arena a;
    uimk2_line line;
    uimk2_layout_item items[1];
    const uimk2_bm *q;
    const uint8_t *qa = &uimk2_glyph_alpha[uimk2_glyph_find('?')->offset];
    (void)make_root(&t, items, 0, CLEAR);
    uimk2_arena_init(&a, arena_buf, sizeof arena_buf);

    /* a two-byte codepoint is one '?' glyph */
    CHECK(uimk2_line_build(&t, &a, &line, "caf\xC3\xA9", 0, INK_COMB, BLACK));
    CHECK(line.idx[4] == 0 && line.idx[3] != 0);
    q = &t.bm[line.idx[3]];
    CHECK(q->u.glyph.alpha == qa);

    /* an invalid byte and a truncated sequence are one '?' each */
    CHECK(uimk2_line_build(&t, &a, &line, "\xFF" "a\xC3", 0, INK_COMB, BLACK));
    CHECK(line.idx[3] == 0);
    CHECK(t.bm[line.idx[0]].u.glyph.alpha == qa);
    CHECK(t.bm[line.idx[1]].u.glyph.alpha ==
          &uimk2_glyph_alpha[uimk2_glyph_find('a')->offset]);
    CHECK(t.bm[line.idx[2]].u.glyph.alpha == qa);

    /* the empty line is a 0 x 0 cache and a bare terminator */
    CHECK(uimk2_line_build(&t, &a, &line, "", 0, INK_COMB, BLACK));
    CHECK(line.idx[0] == 0);
    CHECK(t.bm[line.cache].w == 0 && t.bm[line.cache].h == 0);
    CHECK(line.arena_len == 4u);
}

static void test_line_full_changes_nothing(void) {
    uimk2_bmtab t;
    uimk2_arena a;
    uimk2_line line;
    uimk2_layout_item items[1];
    uint16_t count;
    uint32_t top;
    (void)make_root(&t, items, 0, CLEAR);

    /* arena too small for the cache */
    uimk2_arena_init(&a, arena_buf, 64);
    count = t.count;
    top = a.top;
    CHECK(!uimk2_line_build(&t, &a, &line, "Hello", 1, INK_COMB, BLACK));
    CHECK(t.count == count && a.top == top);

    /* table too small for the headers */
    uimk2_arena_init(&a, arena_buf, sizeof arena_buf);
    t.cap = (uint16_t)(t.count + 3);
    CHECK(!uimk2_line_build(&t, &a, &line, "Hello", 1, INK_COMB, BLACK));
    CHECK(t.count == count && a.top == 0);
    CHECK(uimk2_line_build(&t, &a, &line, "H", 1, INK_COMB, BLACK));
    t.cap = CAP;
}

/* Lines live in the dynamic region: a title rebuilt after rewind(song_mark)
 * starts at song_mark and leaves the album region's cache bytes alone. */
static void test_line_in_dynamic_region(void) {
    uimk2_bmtab t;
    uimk2_arena a;
    uimk2_line artist, album, title;
    uimk2_layout_item items[1];
    static uint8_t snap[ARENA_BYTES];
    uint32_t album_end;
    (void)make_root(&t, items, 0, CLEAR);
    uimk2_arena_init(&a, arena_buf, sizeof arena_buf);
    (void)uimk2_arena_alloc(&a, 40); /* static content */
    uimk2_arena_seal(&a);

    CHECK(uimk2_line_build(&t, &a, &artist, "Artist", 1, INK_COMB, BLACK));
    CHECK(uimk2_line_build(&t, &a, &album, "Album", 1, INK_COMB, BLACK));
    uimk2_arena_mark_song(&a);
    CHECK(artist.arena_off == a.album_mark);
    CHECK(album.arena_off == artist.arena_off + artist.arena_len);
    album_end = a.song_mark;
    CHECK(album_end == album.arena_off + album.arena_len);

    CHECK(uimk2_line_build(&t, &a, &title, "One", 1, INK_COMB, BLACK));
    CHECK(title.arena_off == a.song_mark);
    memcpy(snap, arena_buf, album_end);

    CHECK(uimk2_arena_rewind(&a, a.song_mark));
    CHECK(uimk2_line_build(&t, &a, &title, "Two longer", 1, INK_COMB, BLACK));
    CHECK(title.arena_off == a.song_mark);
    CHECK(memcmp(snap, arena_buf, album_end) == 0);
}

int main(void) {
    test_table_shape();
    test_glyph_find();
    test_glyph_reads_flash();
    test_combiner_set();
    test_line_build_and_tint();
    test_line_utf8();
    test_line_full_changes_nothing();
    test_line_in_dynamic_region();
    printf("test_line: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
