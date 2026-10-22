#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "arena.h"

static int failures = 0;

#define CHECK(cond)                                                          \
    do {                                                                     \
        if (!(cond)) {                                                       \
            fprintf(stderr, "%s:%d: CHECK failed: %s\n", __FILE__, __LINE__, \
                    #cond);                                                  \
            failures++;                                                      \
        }                                                                    \
    } while (0)

/* Emulates the scene rebuild: artist and album, then song_mark, then title. */
static void build_album(Arena *a, uint8_t **artist, uint8_t **album,
                        uint8_t fill)
{
    *artist = arena_alloc(a, 24);
    memset(*artist, fill, 24);
    *album = arena_alloc(a, 40);
    memset(*album, (uint8_t)(fill + 1), 40);
    arena_mark_song(a);
}

static uint8_t *build_song(Arena *a, uint8_t fill)
{
    uint8_t *title = arena_alloc(a, 16);
    memset(title, fill, 16);
    return title;
}

static int bytes_are(const uint8_t *p, uint8_t v, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) {
        if (p[i] != v) {
            return 0;
        }
    }
    return 1;
}

static void test_seal_marks(void)
{
    uint8_t *mem = malloc(4096);
    Arena a;
    arena_init(&a, mem, 4096);
    CHECK(arena_alloc(&a, 6) != NULL);
    CHECK(a.top == 8); /* 6 rounds up to 8 */
    arena_seal_static(&a);
    CHECK(a.static_top == 8);
    CHECK(a.album_mark == 8);
    CHECK(a.song_mark == 8);
    free(mem);
}

static void test_alloc_aligned(void)
{
    uint8_t *mem = malloc(4096);
    Arena a;
    void *p;
    arena_init(&a, mem, 4096);
    p = arena_alloc(&a, 1);
    CHECK(((uintptr_t)p & 3u) == 0);
    p = arena_alloc(&a, 1);
    CHECK(((uintptr_t)p & 3u) == 0);
    CHECK(a.top == 8);
    free(mem);
}

static void test_title_rewind_keeps_album(void)
{
    uint8_t *mem = malloc(4096);
    Arena a;
    uint8_t *artist, *album, *title, *title2;
    arena_init(&a, mem, 4096);
    arena_alloc(&a, 12); /* chrome */
    arena_seal_static(&a);

    build_album(&a, &artist, &album, 0x11);
    title = build_song(&a, 0x21);
    CHECK(title == a.base + a.song_mark);

    CHECK(arena_rewind(&a, ARENA_MARK_SONG) == ARENA_REWIND_OK);
    CHECK(a.top == a.song_mark);
    CHECK(bytes_are(artist, 0x11, 24));
    CHECK(bytes_are(album, 0x12, 40));

    title2 = build_song(&a, 0x22);
    CHECK(title2 == title); /* same slot reused */
    CHECK(bytes_are(artist, 0x11, 24));
    CHECK(bytes_are(album, 0x12, 40));
    CHECK(bytes_are(title2, 0x22, 16));
    free(mem);
}

static void test_album_rewind_drops_title_and_rebuilds(void)
{
    uint8_t *mem = malloc(4096);
    Arena a;
    uint8_t *artist, *album, *artist2, *album2, *title;
    size_t album_region_end;
    arena_init(&a, mem, 4096);
    arena_seal_static(&a);

    build_album(&a, &artist, &album, 0x31);
    title = build_song(&a, 0x41);
    album_region_end = a.song_mark;

    CHECK(arena_rewind(&a, ARENA_MARK_ALBUM) == ARENA_REWIND_OK);
    CHECK(a.top == a.album_mark);
    CHECK(a.song_mark == a.album_mark);

    build_album(&a, &artist2, &album2, 0x51);
    CHECK(artist2 == artist); /* rebuilt in the same place */
    CHECK(album2 == album);
    CHECK(a.song_mark == album_region_end);
    CHECK(bytes_are(artist2, 0x51, 24));
    CHECK(bytes_are(album2, 0x52, 40));

    title = build_song(&a, 0x61);
    CHECK(title == a.base + album_region_end);
    CHECK(bytes_are(title, 0x61, 16));
    free(mem);
}

static void test_keep_above_song_refuses_rewind(void)
{
    uint8_t *mem = malloc(4096);
    Arena a;
    uint8_t *artist, *album, *title, *hole;
    size_t top_before;
    arena_init(&a, mem, 4096);
    arena_seal_static(&a);
    build_album(&a, &artist, &album, 0x71);
    title = build_song(&a, 0x81);
    CHECK(title != NULL);

    hole = arena_alloc_keep(&a, 32);
    CHECK(hole != NULL);
    top_before = a.top;

    CHECK(arena_rewind(&a, ARENA_MARK_SONG) == ARENA_REWIND_REFUSED);
    CHECK(a.top == top_before);
    CHECK(arena_rewind(&a, ARENA_MARK_ALBUM) == ARENA_REWIND_REFUSED);
    CHECK(a.top == top_before);
    CHECK(bytes_are(artist, 0x71, 24));
    CHECK(bytes_are(album, 0x72, 40));

    /* Later allocs go above the hole, not into it. */
    CHECK(arena_alloc(&a, 8) == a.base + top_before);
    free(mem);
}

static void test_overflow_reset_rebuilds_album_then_song(void)
{
    uint8_t *mem = malloc(256);
    Arena a;
    uint8_t *artist, *album, *title, *artist2, *album2, *title2;
    arena_init(&a, mem, 256);
    arena_alloc(&a, 16); /* chrome */
    arena_seal_static(&a);

    build_album(&a, &artist, &album, 0x91);
    title = build_song(&a, 0xa1);
    CHECK(title != NULL);
    CHECK(arena_alloc_keep(&a, 16) != NULL);

    /* The keep block blocks the title rewind; a big alloc overflows the cap. */
    CHECK(arena_rewind(&a, ARENA_MARK_SONG) == ARENA_REWIND_REFUSED);
    CHECK(arena_alloc(&a, 200) == NULL);
    CHECK(a.top == 16 + 24 + 40 + 16 + 16);

    /* The reset: rewind to static_top, rebuild album, then song. */
    CHECK(arena_rewind(&a, ARENA_MARK_STATIC) == ARENA_REWIND_OK);
    CHECK(a.top == a.static_top);
    CHECK(a.keep_top == 0);
    build_album(&a, &artist2, &album2, 0xb1);
    CHECK(artist2 == a.base + a.static_top);
    CHECK(album2 == artist2 + 24);
    CHECK(bytes_are(artist2, 0xb1, 24));
    CHECK(bytes_are(album2, 0xb2, 40));
    title2 = build_song(&a, 0xc1);
    CHECK(title2 == a.base + a.song_mark);
    CHECK(bytes_are(title2, 0xc1, 16));
    free(mem);
}

static void test_rewind_refuses_nothing_when_clean(void)
{
    uint8_t *mem = malloc(4096);
    Arena a;
    uint8_t *artist, *album;
    arena_init(&a, mem, 4096);
    arena_seal_static(&a);
    build_album(&a, &artist, &album, 0x01);
    CHECK(arena_rewind(&a, ARENA_MARK_SONG) == ARENA_REWIND_OK);
    CHECK(arena_rewind(&a, ARENA_MARK_ALBUM) == ARENA_REWIND_OK);
    CHECK(a.top == a.static_top);
    free(mem);
}

int main(void)
{
    test_seal_marks();
    test_alloc_aligned();
    test_title_rewind_keeps_album();
    test_album_rewind_drops_title_and_rebuilds();
    test_keep_above_song_refuses_rewind();
    test_overflow_reset_rebuilds_album_then_song();
    test_rewind_refuses_nothing_when_clean();

    if (failures) {
        fprintf(stderr, "test_arena: %d check(s) failed\n", failures);
        return 1;
    }
    printf("test_arena: all checks passed\n");
    return 0;
}
