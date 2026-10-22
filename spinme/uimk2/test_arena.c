/* Host test for the bump arena. Build and run: make -C spinme test */
#include <stdio.h>
#include <string.h>

#include "arena.h"

static int failures = 0;
#define CHECK(c)                                                  \
  do {                                                            \
    if (!(c)) {                                                   \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c);         \
      failures++;                                                 \
    }                                                             \
  } while (0)

enum { CAP = 1024, STATIC_BYTES = 100 };
static uint32_t backing[CAP / 4];

/* Scene: artist+album region, then title region. Each text is stored as a
 * string block. Mirrors the rebuild order in uimk2.txt. */
typedef struct {
  Arena a;
  const char *artist, *album, *title;
  char *artist_p, *album_p, *title_p;
} Scene;

static bool put(Scene *s, char **dst, const char *text) {
  size_t n = strlen(text) + 1;
  char *p = arena_alloc(&s->a, n);
  if (!p) {
    return false;
  }
  memcpy(p, text, n);
  *dst = p;
  return true;
}

static bool build_album(Scene *s) {
  bool ok = put(s, &s->artist_p, s->artist) && put(s, &s->album_p, s->album);
  if (ok) {
    arena_end_album(&s->a);
  }
  return ok;
}

static bool build_title(Scene *s) {
  bool ok = put(s, &s->title_p, s->title);
  if (ok) {
    arena_end_title(&s->a);
  }
  return ok;
}

/* On overflow: rewind to static_top, rebuild album then song. */
static bool rebuild_all(Scene *s) {
  CHECK(arena_rewind(&s->a, s->a.static_top));
  return build_album(s) && build_title(s);
}

static void set_title(Scene *s, const char *title) {
  s->title = title;
  if (!arena_rewind(&s->a, s->a.song_mark) || !build_title(s)) {
    rebuild_all(s);
  }
}

static void set_artist_album(Scene *s, const char *artist, const char *album) {
  s->artist = artist;
  s->album = album;
  if (!arena_rewind(&s->a, s->a.album_mark) || !build_album(s) ||
      !build_title(s)) {
    rebuild_all(s);
  }
}

static void scene_init(Scene *s) {
  memset(s, 0, sizeof *s);
  arena_init(&s->a, backing, CAP);
  CHECK(arena_alloc(&s->a, STATIC_BYTES) != NULL);
  arena_seal(&s->a);
  s->artist = "Artist";
  s->album = "Album";
  s->title = "Title";
  CHECK(build_album(s));
  CHECK(build_title(s));
}

static void test_alignment_and_cap(void) {
  Arena a;
  arena_init(&a, backing, 16);
  CHECK(arena_alloc(&a, 1) == (void *)backing);
  CHECK(a.top == 4);
  CHECK(arena_alloc(&a, 5) == (void *)((uint8_t *)backing + 4));
  CHECK(a.top == 12);
  CHECK(arena_alloc(&a, 5) == NULL);
  CHECK(a.top == 12);
  CHECK(arena_alloc(&a, 4) != NULL);
  CHECK(a.top == 16);
  CHECK(arena_alloc(&a, 1) == NULL);
}

static void test_seal_and_marks(void) {
  Scene s;
  scene_init(&s);
  CHECK(s.a.static_top == STATIC_BYTES);
  CHECK(s.a.album_mark == s.a.static_top);
  CHECK(s.a.song_mark > s.a.album_mark);
  CHECK(s.a.top > s.a.song_mark);
  CHECK(s.a.title_end == s.a.top);
  CHECK(!s.a.hole);
  /* Never below static_top: arbitrary and sub-static marks are refused. */
  size_t top = s.a.top;
  CHECK(!arena_rewind(&s.a, 0));
  CHECK(!arena_rewind(&s.a, s.a.static_top - 4));
  CHECK(!arena_rewind(&s.a, s.a.song_mark + 4));
  CHECK(s.a.top == top);
  /* Rewind before seal is refused. */
  Arena u;
  arena_init(&u, backing, CAP);
  arena_alloc(&u, 8);
  CHECK(!arena_rewind(&u, 0));
  CHECK(u.top == 8);
}

static void test_title_rewind_keeps_album(void) {
  Scene s;
  scene_init(&s);
  size_t album_end = s.a.song_mark;
  char *artist_p = s.artist_p, *album_p = s.album_p;
  set_title(&s, "Another Title");
  CHECK(s.a.song_mark == album_end);
  CHECK(s.artist_p == artist_p && s.album_p == album_p);
  CHECK(strcmp(s.artist_p, "Artist") == 0);
  CHECK(strcmp(s.album_p, "Album") == 0);
  CHECK(strcmp(s.title_p, "Another Title") == 0);
  CHECK((uint8_t *)s.title_p == (uint8_t *)backing + album_end);
  /* Repeated title changes do not grow top. */
  size_t top = s.a.top;
  set_title(&s, "Another Title");
  CHECK(s.a.top == top);
}

static void test_album_rewind_drops_title(void) {
  Scene s;
  scene_init(&s);
  set_artist_album(&s, "Different Artist", "Different Album");
  CHECK(strcmp(s.artist_p, "Different Artist") == 0);
  CHECK(strcmp(s.album_p, "Different Album") == 0);
  CHECK(strcmp(s.title_p, "Title") == 0);
  CHECK((uint8_t *)s.artist_p == (uint8_t *)backing + s.a.static_top);
  CHECK(s.a.song_mark == s.a.static_top + 20 + 16);
  CHECK(s.a.top == s.a.song_mark + 8);
  CHECK(!s.a.hole);
}

static void test_hole_refuses_song_rewind(void) {
  Scene s;
  scene_init(&s);
  size_t song = s.a.song_mark;
  CHECK(arena_alloc(&s.a, 8) != NULL); /* stray alloc above the title */
  CHECK(s.a.hole);
  size_t top = s.a.top;
  CHECK(!arena_rewind(&s.a, song));
  CHECK(s.a.top == top);
  CHECK(s.a.song_mark == song);
  /* Title text still intact: the old block stays. */
  CHECK(strcmp(s.title_p, "Title") == 0);
  /* Album rewind and static rewind remain legal and clear the hole. */
  CHECK(arena_rewind(&s.a, s.a.album_mark));
  CHECK(!s.a.hole);
  CHECK(s.a.top == s.a.static_top);

  scene_init(&s);
  CHECK(arena_alloc(&s.a, 8) != NULL);
  CHECK(arena_rewind(&s.a, s.a.static_top));
  CHECK(!s.a.hole);
  CHECK(s.a.top == s.a.static_top);
}

static void test_overflow_resets_to_static(void) {
  Scene s;
  scene_init(&s);
  /* Stray allocs eat the headroom, leaving a hole above the title. */
  while (arena_alloc(&s.a, 64) != NULL) {
  }
  CHECK(s.a.hole);
  CHECK(!arena_rewind(&s.a, s.a.song_mark));
  /* Title change cannot rewind to song_mark: reclaim by full reset. */
  set_title(&s, "Recovered Title");
  CHECK(!s.a.hole);
  CHECK(s.a.album_mark == s.a.static_top);
  CHECK(s.a.top == s.a.song_mark + 16);
  CHECK(strcmp(s.artist_p, "Artist") == 0);
  CHECK(strcmp(s.album_p, "Album") == 0);
  CHECK(strcmp(s.title_p, "Recovered Title") == 0);
  CHECK((uint8_t *)s.artist_p == (uint8_t *)backing + s.a.static_top);
  CHECK(s.artist_p < s.album_p && s.album_p < s.title_p);

  /* A title too large for the cap overflows even after a rewind, and the
   * rebuild falls back to static_top (title does not fit: build fails). */
  scene_init(&s);
  char big[CAP];
  memset(big, 'x', sizeof big - 1);
  big[sizeof big - 1] = '\0';
  s.title = big;
  CHECK(arena_rewind(&s.a, s.a.song_mark));
  CHECK(!build_title(&s));
  CHECK(rebuild_all(&s) == false);
  CHECK(s.a.top == s.a.song_mark);
  CHECK(strcmp(s.artist_p, "Artist") == 0);
}

int main(void) {
  test_alignment_and_cap();
  test_seal_and_marks();
  test_title_rewind_keeps_album();
  test_album_rewind_drops_title();
  test_hole_refuses_song_rewind();
  test_overflow_resets_to_static();
  if (failures) {
    printf("%d failure(s)\n", failures);
    return 1;
  }
  printf("arena: all tests passed\n");
  return 0;
}
