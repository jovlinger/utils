#include "arena.h"

static size_t align4(size_t n)
{
    return (n + 3u) & ~(size_t)3u;
}

void arena_init(Arena *a, uint8_t *base, size_t cap)
{
    a->base = base;
    a->cap = cap;
    a->top = 0;
    a->static_top = 0;
    a->album_mark = 0;
    a->song_mark = 0;
    a->keep_top = 0;
}

static void *alloc_raw(Arena *a, size_t n, int keep)
{
    size_t start = align4(a->top);
    size_t len = align4(n);

    if (start > a->cap || len > a->cap - start) {
        return NULL;
    }
    a->top = start + len;
    if (keep) {
        a->keep_top = a->top;
    }
    return a->base + start;
}

void *arena_alloc(Arena *a, size_t n)
{
    return alloc_raw(a, n, 0);
}

void *arena_alloc_keep(Arena *a, size_t n)
{
    return alloc_raw(a, n, 1);
}

void arena_seal_static(Arena *a)
{
    a->static_top = a->top;
    a->album_mark = a->top;
    a->song_mark = a->top;
    a->keep_top = 0;
}

void arena_mark_song(Arena *a)
{
    a->song_mark = a->top;
}

int arena_rewind(Arena *a, ArenaMark mark)
{
    switch (mark) {
    case ARENA_MARK_STATIC:
        a->top = a->static_top;
        a->album_mark = a->static_top;
        a->song_mark = a->static_top;
        a->keep_top = 0;
        return ARENA_REWIND_OK;
    case ARENA_MARK_ALBUM:
        if (a->keep_top > a->song_mark) {
            return ARENA_REWIND_REFUSED;
        }
        a->top = a->album_mark;
        a->song_mark = a->album_mark;
        return ARENA_REWIND_OK;
    case ARENA_MARK_SONG:
        if (a->keep_top > a->song_mark) {
            return ARENA_REWIND_REFUSED;
        }
        a->top = a->song_mark;
        return ARENA_REWIND_OK;
    }
    return ARENA_REWIND_REFUSED;
}
