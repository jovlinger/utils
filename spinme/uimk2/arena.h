/* Bump arena for the uimk2 bitmap compositor. Host-testable, no libc
 * allocation. See todo 2d255758 (uimk2 bitmap compositor), Bump arena. */
#ifndef UIMK2_ARENA_H
#define UIMK2_ARENA_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
  ARENA_MARK_STATIC = 0, /* static_top: sealed base, never rewound below */
  ARENA_MARK_ALBUM = 1,  /* album_mark: start of artist + album region */
  ARENA_MARK_SONG = 2    /* song_mark: start of the title region */
} ArenaMark;

typedef enum {
  ARENA_DYN = 0,  /* line-owned bytes; freed by rewinding past them */
  ARENA_KEEP = 1  /* must survive; blocks any rewind that would drop it */
} ArenaKind;

typedef struct {
  uint8_t *base;
  size_t cap;
  size_t top;
  size_t static_top;
  size_t album_mark;
  size_t song_mark;
  size_t keep_top; /* end of the highest ARENA_KEEP alloc made after sealing */
  int sealed;
} Arena;

void arena_init(Arena *a, void *buf, size_t cap);

/* Advance top by n rounded up to 4. NULL when it would pass cap. Never
 * rewinds on its own. */
void *arena_alloc(Arena *a, size_t n, ArenaKind kind);

/* Seal static_top at the current top. album_mark = song_mark = static_top.
 * Returns 0 on success, -1 if already sealed. */
int arena_seal(Arena *a);

/* Record the current top as song_mark: the album region is complete. */
void arena_set_song_mark(Arena *a);

/* Rewind top to the named mark. Refused (returns -1, nothing changes) before
 * seal, or when an ARENA_KEEP alloc sits above that mark. Rewinding to
 * album_mark also resets song_mark to album_mark. */
int arena_rewind(Arena *a, ArenaMark which);

/* Overflow reclamation: unconditional rewind to static_top, forgetting every
 * hole. The only way to reclaim a refused-rewind hole. */
void arena_reset(Arena *a);

#endif
