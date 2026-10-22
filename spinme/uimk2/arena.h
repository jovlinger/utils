/* Bump arena for the uimk2 bitmap compositor. See spinme/uimk2.txt.
 * One arena, no lock. Allocation advances top, aligned to 4. */
#ifndef UIMK2_ARENA_H
#define UIMK2_ARENA_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct {
  uint8_t *buf;
  size_t cap;
  size_t top;
  size_t static_top;  /* sealed after chrome, root buffer, fixed text, headers */
  size_t album_mark;  /* start of the artist+album region */
  size_t song_mark;   /* start of the title region */
  size_t title_end;   /* top after the title; allocs beyond it are holes */
  bool sealed;
  bool album_open;    /* album_mark region still being built */
  bool title_open;    /* title region still being built */
  bool hole;          /* an alloc sits above the title */
} Arena;

/* buf must be 4-aligned. */
void arena_init(Arena *a, void *buf, size_t cap);

/* Returns NULL when top would pass cap. Memory is not zeroed. */
void *arena_alloc(Arena *a, size_t n);

/* Seal static_top. album_mark = song_mark = static_top; album region opens. */
void arena_seal(Arena *a);

/* Close the artist+album region: song_mark = top; title region opens. */
void arena_end_album(Arena *a);

/* Close the title region: title_end = top. Later allocs are holes. */
void arena_end_title(Arena *a);

/* Legal only for static_top, album_mark, or song_mark, and only when nothing
 * that must survive sits above the mark. Returns false and changes nothing
 * when refused.
 *  - static_top: always legal once sealed; reopens the album region.
 *  - album_mark: legal; drops title and holes; reopens the album region.
 *  - song_mark: refused while a hole sits above the title; reopens the title
 *    region and keeps the album region. */
bool arena_rewind(Arena *a, size_t mark);

#endif
