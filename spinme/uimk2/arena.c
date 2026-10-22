#include "arena.h"

void arena_init(Arena *a, void *buf, size_t cap) {
  a->buf = (uint8_t *)buf;
  a->cap = cap & ~(size_t)3;
  a->top = 0;
  a->static_top = 0;
  a->album_mark = 0;
  a->song_mark = 0;
  a->title_end = 0;
  a->sealed = false;
  a->album_open = false;
  a->title_open = false;
  a->hole = false;
}

void *arena_alloc(Arena *a, size_t n) {
  size_t need = (n + 3) & ~(size_t)3;
  if (need < n || need > a->cap - a->top) {
    return NULL;
  }
  void *p = a->buf + a->top;
  a->top += need;
  if (a->sealed && !a->album_open && !a->title_open) {
    a->hole = true;
  }
  return p;
}

void arena_seal(Arena *a) {
  a->sealed = true;
  a->static_top = a->top;
  a->album_mark = a->top;
  a->song_mark = a->top;
  a->title_end = a->top;
  a->album_open = true;
  a->title_open = false;
  a->hole = false;
}

void arena_end_album(Arena *a) {
  a->song_mark = a->top;
  a->title_end = a->top;
  a->album_open = false;
  a->title_open = true;
}

void arena_end_title(Arena *a) {
  a->title_end = a->top;
  a->title_open = false;
}

bool arena_rewind(Arena *a, size_t mark) {
  if (!a->sealed) {
    return false;
  }
  if (mark == a->static_top) {
    a->top = mark;
    a->album_mark = mark;
    a->song_mark = mark;
    a->title_end = mark;
    a->album_open = true;
    a->title_open = false;
    a->hole = false;
    return true;
  }
  if (mark == a->album_mark) {
    a->top = mark;
    a->song_mark = mark;
    a->title_end = mark;
    a->album_open = true;
    a->title_open = false;
    a->hole = false;
    return true;
  }
  if (mark == a->song_mark && !a->album_open && !a->hole) {
    a->top = mark;
    a->title_end = mark;
    a->title_open = true;
    return true;
  }
  return false;
}
