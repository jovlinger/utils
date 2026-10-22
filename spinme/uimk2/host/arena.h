/*
 * Bump arena for the uimk2 bitmap heap.
 *
 * Allocation advances top, rounded to 4 bytes. Sealed marks: static_top,
 * album_mark (artist and album region), song_mark (title region). Rewind is
 * legal only to one of those marks. A keep allocation sits above song_mark
 * and is not freed by rewind; a rewind that would drop it is refused and
 * leaves the block as a hole. Only a rewind to static_top reclaims holes.
 */
#ifndef UIMK2_ARENA_H
#define UIMK2_ARENA_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    ARENA_MARK_STATIC = 0, /* rewind here is the reset */
    ARENA_MARK_ALBUM = 1,
    ARENA_MARK_SONG = 2
} ArenaMark;

typedef struct {
    uint8_t *base;
    size_t cap;
    size_t top;
    size_t static_top;
    size_t album_mark;
    size_t song_mark;
    size_t keep_top; /* end of the highest keep alloc, 0 if none */
} Arena;

#define ARENA_REWIND_OK 0
#define ARENA_REWIND_REFUSED (-1)

void arena_init(Arena *a, uint8_t *base, size_t cap);

/* Freeable allocation. Returns NULL and changes nothing if cap would be passed. */
void *arena_alloc(Arena *a, size_t n);

/* Allocation that rewind will not free until a reset to static_top. */
void *arena_alloc_keep(Arena *a, size_t n);

/* Seal static chrome: static_top = album_mark = song_mark = top. */
void arena_seal_static(Arena *a);

/* Record song_mark = top after the artist and album region is built. */
void arena_mark_song(Arena *a);

int arena_rewind(Arena *a, ArenaMark mark);

#endif
