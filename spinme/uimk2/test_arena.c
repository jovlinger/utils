/* Host tests for the uimk2 bump arena and dynamic text stack. */
#include "uimk2_arena.h"

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

#define STATIC_BYTES 100u /* rounds to 100; deliberately not a power of 2 */
#define STATIC_FILL 0xA5

static uint32_t buf_words[4096]; /* 16 KiB, 4-aligned */

static uint32_t aligned(uint32_t n) { return (n + 3u) & ~3u; }
static uint32_t line_size(const char *s) {
    return aligned((uint32_t)strlen(s) + 1u);
}

/* Arena with STATIC_BYTES of static content filled with STATIC_FILL, then
 * sealed. */
static void setup(uimk2_arena *a, uint32_t cap) {
    uint8_t *s;
    memset(buf_words, 0, sizeof buf_words);
    uimk2_arena_init(a, buf_words, cap);
    s = (uint8_t *)uimk2_arena_alloc(a, 30);
    memset(s, STATIC_FILL, aligned(30));
    s = (uint8_t *)uimk2_arena_alloc_pinned(a, STATIC_BYTES - aligned(30));
    memset(s, STATIC_FILL, STATIC_BYTES - aligned(30));
    uimk2_arena_seal(a);
}

static int static_intact(const uimk2_arena *a) {
    uint32_t i;
    for (i = 0; i < a->static_top; i++) {
        if (a->base[i] != STATIC_FILL) {
            return 0;
        }
    }
    return 1;
}

static void test_seal_marks(void) {
    uimk2_arena a;
    void *p;
    setup(&a, sizeof buf_words);
    CHECK(a.sealed);
    CHECK(a.static_top == STATIC_BYTES);
    CHECK(a.album_mark == a.static_top);
    CHECK(a.song_mark == a.static_top);
    CHECK(a.pinned_top == 0); /* pinned before seal is plain static */

    p = uimk2_arena_alloc(&a, 1);
    CHECK(uimk2_arena_off(&a, p) == STATIC_BYTES);
    CHECK(a.top == STATIC_BYTES + 4u);
    p = uimk2_arena_alloc(&a, 5);
    CHECK(uimk2_arena_off(&a, p) % 4u == 0);
    CHECK(a.top == STATIC_BYTES + 12u);

    /* Not a mark, below static_top, above top: all refused. */
    CHECK(!uimk2_arena_rewind(&a, STATIC_BYTES + 4u));
    CHECK(!uimk2_arena_rewind(&a, STATIC_BYTES - 4u));
    CHECK(!uimk2_arena_rewind(&a, 0));
    CHECK(a.top == STATIC_BYTES + 12u);
    CHECK(uimk2_arena_rewind(&a, a.static_top));
    CHECK(a.top == STATIC_BYTES);

    /* Seal is once only. */
    (void)uimk2_arena_alloc(&a, 8);
    uimk2_arena_seal(&a);
    CHECK(a.static_top == STATIC_BYTES);

    /* Unsealed arena refuses rewind. */
    uimk2_arena_init(&a, buf_words, sizeof buf_words);
    CHECK(!uimk2_arena_rewind(&a, 0));
    CHECK(static_intact(&a));
}

static void test_alloc_past_cap(void) {
    uimk2_arena a;
    uint32_t top;
    setup(&a, 128);
    top = a.top;
    CHECK(uimk2_arena_alloc(&a, 29) == NULL);
    CHECK(a.top == top);
    CHECK(uimk2_arena_alloc(&a, 0xFFFFFFFFu) == NULL);
    CHECK(uimk2_arena_alloc(&a, 28) != NULL);
    CHECK(a.top == 128);
}

static void test_title_rewind_keeps_album_region(void) {
    uimk2_arena a;
    uimk2_track_text t;
    uint8_t album_region[256];
    uint32_t album_len;
    char *artist, *album;

    setup(&a, sizeof buf_words);
    uimk2_track_text_init(&t, &a);
    CHECK(uimk2_track_text_set(&t, "Miles Davis", "Kind of Blue", "So What") ==
          UIMK2_TT_ALBUM);
    CHECK(uimk2_arena_off(&a, t.artist) == a.album_mark);
    CHECK(a.song_mark == a.album_mark + line_size("Miles Davis") +
                             line_size("Kind of Blue"));
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);

    album_len = a.song_mark - a.album_mark;
    memcpy(album_region, a.base + a.album_mark, album_len);
    artist = t.artist;
    album = t.album;

    CHECK(uimk2_track_text_set(&t, "Miles Davis", "Kind of Blue",
                               "Freddie Freeloader, a longer title") ==
          UIMK2_TT_TITLE);
    CHECK(memcmp(album_region, a.base + a.album_mark, album_len) == 0);
    CHECK(t.artist == artist);
    CHECK(t.album == album);
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
    CHECK(strcmp(t.title, "Freddie Freeloader, a longer title") == 0);
    CHECK(a.top == a.song_mark + line_size("Freddie Freeloader, a longer title"));

    /* Shorter title goes back to the same slot. */
    CHECK(uimk2_track_text_set(&t, "Miles Davis", "Kind of Blue", "Blue") ==
          UIMK2_TT_TITLE);
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
    CHECK(a.top == a.song_mark + line_size("Blue"));
    CHECK(memcmp(album_region, a.base + a.album_mark, album_len) == 0);
    CHECK(static_intact(&a));
    CHECK(t.resets == 0);
}

static void test_album_rewind_rebuilds_title(void) {
    uimk2_arena a;
    uimk2_track_text t;
    uint32_t old_song;

    setup(&a, sizeof buf_words);
    uimk2_track_text_init(&t, &a);
    (void)uimk2_track_text_set(&t, "A", "B", "Title One");
    old_song = a.song_mark;

    /* Artist change: rewind to album_mark, rebuild artist, album, title. */
    CHECK(uimk2_track_text_set(&t, "A much longer artist", "B", "Title One") ==
          UIMK2_TT_ALBUM);
    CHECK(uimk2_arena_off(&a, t.artist) == a.album_mark);
    CHECK(uimk2_arena_off(&a, t.album) ==
          a.album_mark + line_size("A much longer artist"));
    CHECK(a.song_mark == a.album_mark + line_size("A much longer artist") +
                             line_size("B"));
    CHECK(a.song_mark > old_song);
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
    CHECK(strcmp(t.artist, "A much longer artist") == 0);
    CHECK(strcmp(t.album, "B") == 0);
    CHECK(strcmp(t.title, "Title One") == 0);
    CHECK(a.top == a.song_mark + line_size("Title One"));

    /* Album change with a new title. */
    CHECK(uimk2_track_text_set(&t, "A much longer artist", "C", "Two") ==
          UIMK2_TT_ALBUM);
    CHECK(uimk2_arena_off(&a, t.artist) == a.album_mark);
    CHECK(strcmp(t.album, "C") == 0);
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
    CHECK(strcmp(t.title, "Two") == 0);
    CHECK(a.top == a.song_mark + line_size("Two"));
    CHECK(static_intact(&a));
}

static void test_identical_text_no_rewind(void) {
    uimk2_arena a;
    uimk2_track_text t;
    uint32_t top, song;
    char *title;

    setup(&a, sizeof buf_words);
    uimk2_track_text_init(&t, &a);
    (void)uimk2_track_text_set(&t, "A", "B", "C");
    top = a.top;
    song = a.song_mark;
    title = t.title;
    CHECK(uimk2_track_text_set(&t, "A", "B", "C") == UIMK2_TT_SAME);
    CHECK(a.top == top);
    CHECK(a.song_mark == song);
    CHECK(t.title == title);
}

static void test_pinned_alloc_refuses_rewind_and_leaves_hole(void) {
    uimk2_arena a;
    uimk2_track_text t;
    uint8_t album_region[64];
    uint32_t album_len, song, old_title_off, pinned_off;
    uint8_t *pinned;

    setup(&a, sizeof buf_words);
    uimk2_track_text_init(&t, &a);
    (void)uimk2_track_text_set(&t, "Artist", "Album", "Old title");
    song = a.song_mark;
    album_len = song - a.album_mark;
    memcpy(album_region, a.base + a.album_mark, album_len);
    old_title_off = uimk2_arena_off(&a, t.title);

    pinned = (uint8_t *)uimk2_arena_alloc_pinned(&a, 16);
    memset(pinned, 0x5C, 16);
    pinned_off = uimk2_arena_off(&a, pinned);
    CHECK(pinned_off == song + line_size("Old title"));
    CHECK(a.pinned_top == pinned_off + 16u);

    CHECK(!uimk2_arena_rewind(&a, a.song_mark));
    CHECK(!uimk2_arena_rewind(&a, a.album_mark));
    CHECK(!uimk2_arena_rewind(&a, a.static_top));
    CHECK(a.top == pinned_off + 16u);

    CHECK(uimk2_track_text_set(&t, "Artist", "Album", "New title") ==
          UIMK2_TT_TITLE);
    /* Old title bytes stay as a hole; the new title sits above the pin. */
    CHECK(strcmp((const char *)a.base + old_title_off, "Old title") == 0);
    CHECK(uimk2_arena_off(&a, t.title) == pinned_off + 16u);
    CHECK(strcmp(t.title, "New title") == 0);
    CHECK(a.song_mark == song);
    CHECK(memcmp(album_region, a.base + a.album_mark, album_len) == 0);
    {
        int i, ok = 1;
        for (i = 0; i < 16; i++) {
            ok &= pinned[i] == 0x5C;
        }
        CHECK(ok);
    }
    CHECK(t.resets == 0);
    CHECK(static_intact(&a));
}

static void test_overflow_resets_and_rebuilds(void) {
    uimk2_arena a;
    uimk2_track_text t;
    char title[32];
    uint32_t cap = 256;
    int i;

    setup(&a, cap);
    uimk2_track_text_init(&t, &a);
    (void)uimk2_track_text_set(&t, "Artist", "Album", "T0");

    /* Each pin makes the previous title a hole; the stack only grows. */
    for (i = 1; i < 64 && t.resets == 0; i++) {
        (void)uimk2_arena_alloc_pinned(&a, 8); /* NULL near cap is fine */
        snprintf(title, sizeof title, "Title %d", i);
        (void)uimk2_track_text_set(&t, "Artist", "Album", title);
    }
    CHECK(t.resets == 1);
    CHECK(a.pinned_top == 0);
    CHECK(a.album_mark == a.static_top);
    CHECK(uimk2_arena_off(&a, t.artist) == a.static_top);
    CHECK(uimk2_arena_off(&a, t.album) == a.static_top + line_size("Artist"));
    CHECK(a.song_mark == a.static_top + line_size("Artist") + line_size("Album"));
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
    CHECK(strcmp(t.artist, "Artist") == 0);
    CHECK(strcmp(t.album, "Album") == 0);
    CHECK(strcmp(t.title, title) == 0);
    CHECK(a.top == a.song_mark + line_size(title));
    CHECK(a.top <= a.cap);
    CHECK(static_intact(&a));

    /* After the reset, title rewinds work again. */
    CHECK(uimk2_track_text_set(&t, "Artist", "Album", "After") ==
          UIMK2_TT_TITLE);
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
}

static void test_overflow_on_album_change(void) {
    uimk2_arena a;
    uimk2_track_text t;
    uint8_t *pin;

    setup(&a, 160); /* 60 dynamic bytes */
    uimk2_track_text_init(&t, &a);
    (void)uimk2_track_text_set(&t, "Ar", "Al", "Ti");
    pin = (uint8_t *)uimk2_arena_alloc_pinned(&a, 24);
    CHECK(pin != NULL);
    /* Rewind to album_mark is refused by the pin; the new album region does
     * not fit above it, so the stack resets and rebuilds. */
    CHECK(uimk2_track_text_set(&t, "Artist two", "Album two", "Title two") ==
          UIMK2_TT_ALBUM);
    CHECK(t.resets == 1);
    CHECK(uimk2_arena_off(&a, t.artist) == a.static_top);
    CHECK(uimk2_arena_off(&a, t.title) == a.song_mark);
    CHECK(strcmp(t.title, "Title two") == 0);
    CHECK(static_intact(&a));
}

static void test_too_big_fails(void) {
    uimk2_arena a;
    uimk2_track_text t;
    char big[200];

    setup(&a, 160);
    uimk2_track_text_init(&t, &a);
    memset(big, 'x', sizeof big - 1);
    big[sizeof big - 1] = '\0';
    CHECK(uimk2_track_text_set(&t, "A", "B", big) == UIMK2_TT_FAIL);
    CHECK(t.artist == NULL && t.album == NULL && t.title == NULL);
    CHECK(a.top == a.static_top);
    CHECK(static_intact(&a));
}

int main(void) {
    test_seal_marks();
    test_alloc_past_cap();
    test_title_rewind_keeps_album_region();
    test_album_rewind_rebuilds_title();
    test_identical_text_no_rewind();
    test_pinned_alloc_refuses_rewind_and_leaves_hole();
    test_overflow_resets_and_rebuilds();
    test_overflow_on_album_change();
    test_too_big_fails();
    printf("test_arena: %d checks, %d failures\n", checks, failures);
    return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
