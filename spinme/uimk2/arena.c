#include "arena.h"

void arena_init(Arena *a, void *buf, size_t cap) {
  a->base = (uint8_t *)buf;
  a->cap = cap;
  a->top = 0;
  a->static_top = 0;
  a->album_mark = 0;
  a->song_mark = 0;
  a->keep_top = 0;
  a->sealed = 0;
}

void *arena_alloc(Arena *a, size_t n, ArenaKind kind) {
  size_t rounded = (n + 3u) & ~(size_t)3u;
  if (rounded < n || rounded > a->cap - a->top) {
    return NULL;
  }
  void *p = a->base + a->top;
  a->top += rounded;
  if (kind == ARENA_KEEP && a->sealed) {
    a->keep_top = a->top;
  }
  return p;
}

int arena_seal(Arena *a) {
  if (a->sealed) {
    return -1;
  }
  a->sealed = 1;
  a->static_top = a->top;
  a->album_mark = a->top;
  a->song_mark = a->top;
  a->keep_top = a->top;
  return 0;
}

void arena_set_song_mark(Arena *a) {
  if (a->sealed) {
    a->song_mark = a->top;
  }
}

int arena_rewind(Arena *a, ArenaMark which) {
  size_t mark;
  if (!a->sealed) {
    return -1;
  }
  switch (which) {
    case ARENA_MARK_STATIC: mark = a->static_top; break;
    case ARENA_MARK_ALBUM: mark = a->album_mark; break;
    case ARENA_MARK_SONG: mark = a->song_mark; break;
    default: return -1;
  }
  if (a->keep_top > mark) {
    return -1;
  }
  a->top = mark;
  if (which != ARENA_MARK_SONG) {
    a->song_mark = a->album_mark;
  }
  if (which == ARENA_MARK_STATIC) {
    a->album_mark = a->static_top;
    a->song_mark = a->static_top;
  }
  return 0;
}

void arena_reset(Arena *a) {
  if (!a->sealed) {
    return;
  }
  a->top = a->static_top;
  a->album_mark = a->static_top;
  a->song_mark = a->static_top;
  a->keep_top = a->static_top;
}
