/* uimk2 bump arena and the dynamic text stack (artist, album, title).
 *
 * One arena. Allocation advances top, aligned to 4. static_top is sealed
 * after the static content and is never rewound below except by reboot.
 * Above it sit two watermarks: album_mark (== static_top) starts the album
 * region (artist line, then album line), and song_mark is the top after that
 * region, where the title line starts.
 *
 * Portable C99, no platform headers: built by the host tests and by the
 * firmware alike.
 */
#ifndef UIMK2_ARENA_H
#define UIMK2_ARENA_H

#include <stdbool.h>
#include <stdint.h>

#define UIMK2_ARENA_ALIGN 4u

typedef struct {
    uint8_t *base;        /* 4-aligned backing store */
    uint32_t cap;         /* bytes in base */
    uint32_t top;         /* next free offset */
    uint32_t static_top;  /* sealed floor */
    uint32_t album_mark;  /* start of the album region; == static_top */
    uint32_t song_mark;   /* start of the title region */
    uint32_t pinned_top;  /* end of the highest alloc that must survive a
                             dynamic rewind; 0 when there is none */
    bool sealed;
} uimk2_arena;

/* buf must be 4-aligned. */
void uimk2_arena_init(uimk2_arena *a, void *buf, uint32_t cap);

/* Bump-allocate n bytes, rounded up to 4. NULL when top would pass cap;
 * the arena is unchanged then. */
void *uimk2_arena_alloc(uimk2_arena *a, uint32_t n);

/* An alloc that is not part of the dynamic text stack. After seal it must
 * survive: a rewind to any mark below its end is refused, so the bytes a
 * refused rewind would have freed stay as a hole. Only uimk2_arena_reset
 * drops it. Before seal it is an ordinary static alloc. */
void *uimk2_arena_alloc_pinned(uimk2_arena *a, uint32_t n);

/* static_top = album_mark = song_mark = top. Once only. */
void uimk2_arena_seal(uimk2_arena *a);

/* song_mark = top. Called after the album region is built. */
void uimk2_arena_mark_song(uimk2_arena *a);

/* top = mark. Legal only when sealed, mark is static_top, album_mark, or
 * song_mark, mark <= top, and no pinned alloc ends above mark. Returns
 * false and changes nothing otherwise. */
bool uimk2_arena_rewind(uimk2_arena *a, uint32_t mark);

/* The overflow path and the only reclamation: top = album_mark = song_mark
 * = static_top, and pinned allocs are dropped. Every pointer above
 * static_top is invalid afterwards. */
void uimk2_arena_reset(uimk2_arena *a);

/* Offset of p within the arena. */
uint32_t uimk2_arena_off(const uimk2_arena *a, const void *p);

/* ---- dynamic text stack ------------------------------------------------ */

typedef struct {
    uimk2_arena *a;
    char *artist;  /* NUL-terminated copies in the arena, or NULL */
    char *album;
    char *title;
    uint32_t resets;  /* overflow resets taken so far */
} uimk2_track_text;

typedef enum {
    UIMK2_TT_SAME = 0,  /* identical text: no rewind, nothing to dirty */
    UIMK2_TT_TITLE,     /* title rebuilt above song_mark */
    UIMK2_TT_ALBUM,     /* artist, album, and title rebuilt above album_mark */
    UIMK2_TT_FAIL       /* the text does not fit even after a reset */
} uimk2_tt_result;

void uimk2_track_text_init(uimk2_track_text *t, uimk2_arena *a);

/* Apply a new snapshot. An artist or album change rewinds to album_mark and
 * rebuilds artist, album, then title, and moves song_mark. A title-only
 * change rewinds to song_mark and rebuilds the title; the album region bytes
 * stay. A refused rewind leaves the old bytes as a hole and allocates at
 * top. If top would pass cap, reset to static_top and rebuild album then
 * song. The inputs must not point into the arena. */
uimk2_tt_result uimk2_track_text_set(uimk2_track_text *t, const char *artist,
                                     const char *album, const char *title);

#endif /* UIMK2_ARENA_H */
