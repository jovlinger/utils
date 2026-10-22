/* Host test for the bump arena. Build and run: make -C spinme/uimk2 test */
#include <stdio.h>
#include <string.h>

#include "arena.h"

static int failures;

#define CHECK(cond)                                                  \
  do {                                                               \
    if (!(cond)) {                                                   \
      printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);         \
      failures++;                                                    \
    }                                                                \
  } while (0)

#define CAP 1024u
#define STATIC_BYTES 100u /* 100 is already a multiple of 4 */

static uint8_t buf[CAP];
static Arena arena;

/* A text line: bytes allocated from the arena, remembered to check survival. */
typedef struct {
  char *p;
  size_t len;
} Line;

static int line_alloc(Line *l, const char *text, size_t pad) {
  size_t n = strlen(text) + 1 + pad;
  l->p = (char *)arena_alloc(&arena, n, ARENA_DYN);
  l->len = n;
  if (!l->p) {
    return -1;
  }
  memset(l->p, 0, n);
  strcpy(l->p, text);
  return 0;
}

/* Scene driver following the Bump arena rules; pads make regions big enough
 * to exercise overflow. */
typedef struct {
  Line artist, album, title;
  char cur_artist[32], cur_album[32], cur_title[32];
  size_t pad_artist, pad_album, pad_title;
  int resets;
} Scene;

static int build_album(Scene *s) {
  if (line_alloc(&s->artist, s->cur_artist, s->pad_artist) ||
      line_alloc(&s->album, s->cur_album, s->pad_album)) {
    return -1;
  }
  arena_set_song_mark(&arena);
  return 0;
}

static int build_title(Scene *s) {
  return line_alloc(&s->title, s->cur_title, s->pad_title);
}

static void rebuild_all(Scene *s) {
  /* Overflow: reset to static_top, rebuild album then song. */
  arena_reset(&arena);
  s->resets++;
  CHECK(build_album(s) == 0);
  CHECK(build_title(s) == 0);
}

static void scene_set(Scene *s, const char *artist, const char *album,
                      const char *title) {
  int album_changed =
      strcmp(artist, s->cur_artist) != 0 || strcmp(album, s->cur_album) != 0;
  int title_changed = strcmp(title, s->cur_title) != 0;
  if (!album_changed && !title_changed) {
    return; /* identical text: no rewind, no dirty */
  }
  strcpy(s->cur_artist, artist);
  strcpy(s->cur_album, album);
  strcpy(s->cur_title, title);
  if (album_changed) {
    /* A refused rewind leaves a hole; the rebuild allocates above it. */
    (void)arena_rewind(&arena, ARENA_MARK_ALBUM);
    if (build_album(s) != 0 || build_title(s) != 0) {
      rebuild_all(s);
    }
  } else {
    (void)arena_rewind(&arena, ARENA_MARK_SONG);
    if (build_title(s) != 0) {
      rebuild_all(s);
    }
  }
}

static void fresh(void) {
  memset(buf, 0, sizeof buf);
  arena_init(&arena, buf, CAP);
  CHECK(arena_alloc(&arena, STATIC_BYTES, ARENA_KEEP) != NULL);
  CHECK(arena_seal(&arena) == 0);
}

static void test_alloc_alignment(void) {
  Arena a;
  uint8_t b[64];
  arena_init(&a, b, sizeof b);
  void *p1 = arena_alloc(&a, 1, ARENA_DYN);
  void *p2 = arena_alloc(&a, 5, ARENA_DYN);
  void *p3 = arena_alloc(&a, 4, ARENA_DYN);
  CHECK(p1 == b);
  CHECK(p2 == b + 4);
  CHECK(p3 == b + 12);
  CHECK(a.top == 16);
  CHECK(arena_alloc(&a, 49, ARENA_DYN) == NULL); /* 16 + 52 > 64 */
  CHECK(a.top == 16);
  CHECK(arena_alloc(&a, 48, ARENA_DYN) == b + 16);
  CHECK(a.top == 64);
  CHECK(arena_alloc(&a, 1, ARENA_DYN) == NULL);
}

static void test_seal(void) {
  fresh();
  CHECK(arena.static_top == STATIC_BYTES);
  CHECK(arena.album_mark == STATIC_BYTES);
  CHECK(arena.song_mark == STATIC_BYTES);
  CHECK(arena_seal(&arena) == -1); /* sealed once */
  /* Nothing rewinds below static_top: a rewind to static_top is the floor. */
  arena_alloc(&arena, 40, ARENA_DYN);
  CHECK(arena_rewind(&arena, ARENA_MARK_STATIC) == 0);
  CHECK(arena.top == STATIC_BYTES);
  CHECK(arena_rewind(&arena, ARENA_MARK_STATIC) == 0);
  CHECK(arena.top == STATIC_BYTES);
  /* Before seal, rewind is refused. */
  Arena a;
  uint8_t b[32];
  arena_init(&a, b, sizeof b);
  arena_alloc(&a, 8, ARENA_DYN);
  CHECK(arena_rewind(&a, ARENA_MARK_STATIC) == -1);
  CHECK(a.top == 8);
}

static void test_marks(void) {
  fresh();
  Scene s;
  memset(&s, 0, sizeof s);
  strcpy(s.cur_artist, "Artist");
  strcpy(s.cur_album, "Album");
  strcpy(s.cur_title, "Title");
  CHECK(arena.album_mark == STATIC_BYTES);
  CHECK(build_album(&s) == 0);
  size_t region = (strlen("Artist") + 1 + 3u) / 4u * 4u +
                  (strlen("Album") + 1 + 3u) / 4u * 4u;
  CHECK(arena.song_mark == STATIC_BYTES + region);
  CHECK(arena.album_mark == STATIC_BYTES); /* album_mark unmoved */
  CHECK(build_title(&s) == 0);
  CHECK(arena.top > arena.song_mark);
}

static void test_title_rewind_keeps_album(void) {
  fresh();
  Scene s;
  memset(&s, 0, sizeof s);
  scene_set(&s, "Artist", "Album", "Title One");
  size_t song_mark = arena.song_mark;
  char *artist_p = s.artist.p;
  char *album_p = s.album.p;
  CHECK(strcmp(artist_p, "Artist") == 0);
  CHECK(strcmp(album_p, "Album") == 0);
  char *title1 = s.title.p;

  scene_set(&s, "Artist", "Album", "Title Two");
  CHECK(arena.song_mark == song_mark);
  CHECK(arena.album_mark == STATIC_BYTES);
  CHECK(s.artist.p == artist_p && s.album.p == album_p);
  CHECK(strcmp(artist_p, "Artist") == 0); /* bytes intact */
  CHECK(strcmp(album_p, "Album") == 0);
  CHECK(s.title.p == title1); /* title reuses the freed slot */
  CHECK(strcmp(s.title.p, "Title Two") == 0);
  CHECK(s.resets == 0);
}

static void test_album_change_drops_title(void) {
  fresh();
  Scene s;
  memset(&s, 0, sizeof s);
  scene_set(&s, "Artist", "Album", "Title");
  size_t old_song_mark = arena.song_mark;

  /* Album change with a longer album: the song mark moves, title rebuilt. */
  scene_set(&s, "Artist", "A Much Longer Album Name", "Title");
  CHECK(arena.album_mark == STATIC_BYTES);
  CHECK(arena.song_mark > old_song_mark);
  CHECK(strcmp(s.artist.p, "Artist") == 0);
  CHECK(strcmp(s.album.p, "A Much Longer Album Name") == 0);
  CHECK(strcmp(s.title.p, "Title") == 0);
  CHECK((uint8_t *)s.title.p >= buf + arena.song_mark);
  CHECK(s.artist.p == (char *)buf + STATIC_BYTES);

  /* Artist change with same album: also rebuilds everything. */
  scene_set(&s, "Other Artist", "A Much Longer Album Name", "Title");
  CHECK(strcmp(s.artist.p, "Other Artist") == 0);
  CHECK(strcmp(s.album.p, "A Much Longer Album Name") == 0);
  CHECK(strcmp(s.title.p, "Title") == 0);
  CHECK(arena.album_mark == STATIC_BYTES);
  CHECK(s.resets == 0);
}

static void test_identical_text_noop(void) {
  fresh();
  Scene s;
  memset(&s, 0, sizeof s);
  scene_set(&s, "Artist", "Album", "Title");
  Arena before = arena;
  scene_set(&s, "Artist", "Album", "Title");
  CHECK(memcmp(&before, &arena, sizeof arena) == 0);
}

static void test_hole_refuses_song_rewind(void) {
  fresh();
  Scene s;
  memset(&s, 0, sizeof s);
  scene_set(&s, "Artist", "Album", "Title");
  size_t song_mark = arena.song_mark;

  /* Some other alloc above song_mark that must survive. */
  uint8_t *stray = (uint8_t *)arena_alloc(&arena, 16, ARENA_KEEP);
  CHECK(stray != NULL);
  memset(stray, 0xAB, 16);
  size_t top_before = arena.top;

  CHECK(arena_rewind(&arena, ARENA_MARK_SONG) == -1);
  CHECK(arena.top == top_before);
  CHECK(arena.song_mark == song_mark);
  CHECK(stray[0] == 0xAB && stray[15] == 0xAB);

  /* The album mark rewind is refused too: the survivor sits above it. */
  CHECK(arena_rewind(&arena, ARENA_MARK_ALBUM) == -1);
  CHECK(arena.top == top_before);

  /* A title change now cannot reclaim: the new title lands above the hole. */
  scene_set(&s, "Artist", "Album", "Title Two");
  CHECK(strcmp(s.title.p, "Title Two") == 0);
  CHECK(s.title.p > (char *)stray);
  CHECK(arena.top > top_before);
  CHECK(stray[0] == 0xAB && stray[15] == 0xAB);
  CHECK(s.resets == 0); /* a hole is not reclaimed until overflow */
}

static void test_overflow_resets_and_rebuilds(void) {
  fresh();
  Scene s;
  memset(&s, 0, sizeof s);
  s.pad_artist = 100;
  s.pad_album = 100;
  s.pad_title = 300;
  scene_set(&s, "Artist", "Album", "Title 0");
  CHECK(s.resets == 0);
  size_t region_top = arena.top;

  /* A KEEP alloc blocks rewinds, so each title change stacks above it until
   * the cap is passed and the scene falls back to reset + rebuild. */
  CHECK(arena_alloc(&arena, 8, ARENA_KEEP) != NULL);
  char title[32];
  int i;
  for (i = 1; i < 10 && s.resets == 0; i++) {
    snprintf(title, sizeof title, "Title %d", i);
    scene_set(&s, "Artist", "Album", title);
  }
  CHECK(s.resets == 1);
  CHECK(arena.top <= CAP);
  /* After reset the album then title are rebuilt from static_top, in order. */
  CHECK(s.artist.p == (char *)buf + STATIC_BYTES);
  CHECK(s.album.p > s.artist.p);
  CHECK((size_t)(s.title.p - (char *)buf) == arena.song_mark);
  CHECK(strcmp(s.artist.p, "Artist") == 0);
  CHECK(strcmp(s.album.p, "Album") == 0);
  CHECK(strcmp(s.title.p, title) == 0);
  CHECK(arena.top <= region_top + 320);
  CHECK(arena.static_top == STATIC_BYTES);
  /* The hole is gone: song rewind works again. */
  CHECK(arena_rewind(&arena, ARENA_MARK_SONG) == 0);
}

static void test_reset_clears_hole(void) {
  fresh();
  arena_alloc(&arena, 16, ARENA_DYN);
  arena_set_song_mark(&arena);
  arena_alloc(&arena, 8, ARENA_KEEP);
  CHECK(arena_rewind(&arena, ARENA_MARK_SONG) == -1);
  arena_reset(&arena);
  CHECK(arena.top == STATIC_BYTES);
  CHECK(arena.album_mark == STATIC_BYTES);
  CHECK(arena.song_mark == STATIC_BYTES);
  CHECK(arena_rewind(&arena, ARENA_MARK_SONG) == 0);
}

int main(void) {
  test_alloc_alignment();
  test_seal();
  test_marks();
  test_title_rewind_keeps_album();
  test_album_change_drops_title();
  test_identical_text_noop();
  test_hole_refuses_song_rewind();
  test_overflow_resets_and_rebuilds();
  test_reset_clears_hole();
  if (failures) {
    printf("%d failure(s)\n", failures);
    return 1;
  }
  printf("arena: all tests passed\n");
  return 0;
}
