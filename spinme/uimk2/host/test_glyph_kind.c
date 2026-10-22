#include <stdio.h>
#include <string.h>

#include "arena.h"
#include "bitmap.h"
#include "glyph.h"
#include "glyphs_gen.h"

static int failures = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, \
                    #cond);                                                  \
            failures++;                                                      \
        }                                                                    \
    } while (0)

#define MAX_W 64
#define MAX_H 32

static const uint8_t BLACK[3] = {0, 0, 0};
static uint8_t px[MAX_W * MAX_H * 4];

static size_t entry_index(uint16_t cp)
{
    size_t i;
    for (i = 0; i < sizeof glyph_table / sizeof glyph_table[0]; i++) {
        if (glyph_table[i].cp == cp) {
            return i;
        }
    }
    return (size_t)-1;
}

static size_t width_of(uint16_t cp)
{
    return glyph_table[entry_index(cp)].width;
}

static const uint8_t *alpha_of(uint16_t cp)
{
    return glyph_alpha + glyph_table[entry_index(cp)].offset;
}

/* Flash tables are per translation unit, so compare bytes, not pointers. */
static int same_alpha(const BitmapTable *t, uint16_t node, uint16_t cp)
{
    size_t n = (size_t)width_of(cp) * GLYPH_HEIGHT;

    return t->nodes[node].glyph != NULL &&
           memcmp(t->nodes[node].glyph, alpha_of(cp), n) == 0;
}

/* A Glyph node reads its alpha from flash and owns no pixels. Under black
 * paper a white glyph composites to R = G = B = alpha, so a repaint of an
 * owner over the glyph shows the flash bytes exactly. */
static void test_glyph_reads_flash(void)
{
    BitmapTable t;
    uint16_t g, owner;
    BmRect box;
    LayoutItem item;
    uint16_t w, h, x, y;
    int bad = 0;

    bm_init(&t);
    g = glyph_new(&t, 'A');
    CHECK(g != BM_NULL);
    CHECK(t.nodes[g].kind == BM_KIND_GLYPH);
    CHECK(t.nodes[g].pixels == NULL);
    CHECK(t.nodes[g].w == width_of('A'));
    CHECK(t.nodes[g].h == GLYPH_HEIGHT);
    CHECK(same_alpha(&t, g, 'A'));

    w = t.nodes[g].w;
    h = t.nodes[g].h;
    CHECK(w <= MAX_W && h <= MAX_H);
    owner = bm_new(&t, BM_KIND_RGBA, w, h);
    CHECK(owner != BM_NULL);
    bm_set_owner(&t, owner, px, BLACK);
    item.x = 0;
    item.y = 0;
    item.idx = g;
    CHECK(bm_set_children(&t, owner, &item, 1));
    box.x = 0;
    box.y = 0;
    box.w = (int16_t)w;
    box.h = (int16_t)h;
    bm_invalidate(&t, owner, box, 0);
    bm_repaint(&t, owner);

    for (y = 0; y < h; y++) {
        for (x = 0; x < w; x++) {
            const uint8_t *p = px + ((size_t)y * w + x) * 4u;
            uint8_t a = alpha_of('A')[(size_t)y * w + x];
            if (p[0] != a || p[1] != a || p[2] != a || p[3] != 255) {
                bad++;
            }
        }
    }
    CHECK(bad == 0);
}

static void test_missing_codepoint_uses_fallback(void)
{
    BitmapTable t;
    uint16_t g;

    bm_init(&t);
    g = glyph_new(&t, 0x0100);
    CHECK(g != BM_NULL);
    CHECK(same_alpha(&t, g, '?'));
    CHECK(t.nodes[g].w == width_of('?'));
    CHECK(t.nodes[g].h == GLYPH_HEIGHT);
}

/* A line is a zero-terminated IdxList and one RGBA cache, both in the arena.
 * Glyph nodes take no arena bytes, so the arena grows by exactly the list
 * and the cache. */
static void test_line_is_idxlist_plus_cache(void)
{
    static uint8_t arena_buf[4096];
    Arena a;
    BitmapTable t;
    GlyphLine line;
    const char *text = "Ab c";
    uint16_t hsep = 1;
    size_t before, used, want_w, i;
    uint8_t *lo, *hi;

    arena_init(&a, arena_buf, sizeof arena_buf);
    bm_init(&t);
    before = a.top;
    CHECK(glyph_line(&a, &t, text, hsep, BLACK, &line));

    for (i = 0; i < 4; i++) {
        uint16_t gi = line.idx[i];
        CHECK(gi != BM_NULL);
        CHECK(t.nodes[gi].kind == BM_KIND_GLYPH);
        CHECK(t.nodes[gi].pixels == NULL);
    }
    CHECK(line.idx[4] == 0);
    CHECK(same_alpha(&t, line.idx[0], 'A'));
    CHECK(same_alpha(&t, line.idx[1], 'b'));
    CHECK(same_alpha(&t, line.idx[2], ' '));
    CHECK(same_alpha(&t, line.idx[3], 'c'));

    want_w = width_of('A') + width_of('b') + width_of(' ') + width_of('c') +
             3u * hsep;
    CHECK(t.nodes[line.cache].kind == BM_KIND_RGBA);
    CHECK(t.nodes[line.cache].w == want_w);
    CHECK(t.nodes[line.cache].h == GLYPH_HEIGHT);
    CHECK(t.nodes[line.cache].pixels != NULL);

    used = a.top - before;
    /* IdxList: 5 uint16 entries, rounded to 4 bytes. Cache: w * h * 4. */
    CHECK(used == 12u + want_w * GLYPH_HEIGHT * 4u);

    lo = arena_buf;
    hi = arena_buf + sizeof arena_buf;
    CHECK(t.nodes[line.cache].pixels >= lo && t.nodes[line.cache].pixels < hi);
}

static void test_line_fails_when_arena_full(void)
{
    static uint8_t tiny[4];
    Arena a;
    BitmapTable t;
    GlyphLine line;

    arena_init(&a, tiny, sizeof tiny);
    bm_init(&t);
    CHECK(!glyph_line(&a, &t, "abcdef", 0, BLACK, &line));
}

int main(void)
{
    test_glyph_reads_flash();
    test_missing_codepoint_uses_fallback();
    test_line_is_idxlist_plus_cache();
    test_line_fails_when_arena_full();
    if (failures) {
        fprintf(stderr, "%d check(s) failed\n", failures);
        return 1;
    }
    printf("test_glyph_kind: all checks passed\n");
    return 0;
}
