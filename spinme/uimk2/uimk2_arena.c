#include "uimk2_arena.h"

#include <stddef.h>
#include <string.h>

static uint32_t align_up(uint32_t n) {
    return (n + (UIMK2_ARENA_ALIGN - 1u)) & ~(UIMK2_ARENA_ALIGN - 1u);
}

void uimk2_arena_init(uimk2_arena *a, void *buf, uint32_t cap) {
    a->base = (uint8_t *)buf;
    a->cap = cap & ~(UIMK2_ARENA_ALIGN - 1u);
    a->top = 0;
    a->static_top = 0;
    a->album_mark = 0;
    a->song_mark = 0;
    a->pinned_top = 0;
    a->sealed = false;
}

void *uimk2_arena_alloc(uimk2_arena *a, uint32_t n) {
    uint32_t need;
    void *p;
    if (n > a->cap) {
        return NULL;
    }
    need = align_up(n);
    if (need > a->cap - a->top) {
        return NULL;
    }
    p = a->base + a->top;
    a->top += need;
    return p;
}

void *uimk2_arena_alloc_pinned(uimk2_arena *a, uint32_t n) {
    void *p = uimk2_arena_alloc(a, n);
    if (p != NULL && a->sealed) {
        a->pinned_top = a->top;
    }
    return p;
}

void uimk2_arena_seal(uimk2_arena *a) {
    if (a->sealed) {
        return;
    }
    a->static_top = a->top;
    a->album_mark = a->top;
    a->song_mark = a->top;
    a->sealed = true;
}

void uimk2_arena_mark_song(uimk2_arena *a) {
    a->song_mark = a->top;
}

bool uimk2_arena_rewind(uimk2_arena *a, uint32_t mark) {
    if (!a->sealed) {
        return false;
    }
    if (mark != a->static_top && mark != a->album_mark && mark != a->song_mark) {
        return false;
    }
    if (mark > a->top || a->pinned_top > mark) {
        return false;
    }
    a->top = mark;
    return true;
}

void uimk2_arena_reset(uimk2_arena *a) {
    a->top = a->static_top;
    a->album_mark = a->static_top;
    a->song_mark = a->static_top;
    a->pinned_top = 0;
}

uint32_t uimk2_arena_off(const uimk2_arena *a, const void *p) {
    return (uint32_t)((const uint8_t *)p - a->base);
}

/* ---- dynamic text stack ------------------------------------------------ */

void uimk2_track_text_init(uimk2_track_text *t, uimk2_arena *a) {
    t->a = a;
    t->artist = NULL;
    t->album = NULL;
    t->title = NULL;
    t->resets = 0;
}

static char *copy_line(uimk2_arena *a, const char *s) {
    size_t len = strlen(s);
    char *p;
    if (len >= UINT32_MAX) {
        return NULL;
    }
    p = (char *)uimk2_arena_alloc(a, (uint32_t)len + 1u);
    if (p != NULL) {
        memcpy(p, s, len + 1u);
    }
    return p;
}

static bool same(const char *cur, const char *s) {
    return cur != NULL && strcmp(cur, s) == 0;
}

static bool build_album(uimk2_track_text *t, const char *artist,
                        const char *album) {
    t->artist = copy_line(t->a, artist);
    if (t->artist == NULL) {
        return false;
    }
    t->album = copy_line(t->a, album);
    if (t->album == NULL) {
        return false;
    }
    uimk2_arena_mark_song(t->a);
    return true;
}

static bool build_title(uimk2_track_text *t, const char *title) {
    t->title = copy_line(t->a, title);
    return t->title != NULL;
}

/* Reset to static_top and rebuild album then song from the inputs. */
static uimk2_tt_result rebuild_after_reset(uimk2_track_text *t,
                                           const char *artist,
                                           const char *album,
                                           const char *title) {
    uimk2_arena_reset(t->a);
    t->resets++;
    if (!build_album(t, artist, album) || !build_title(t, title)) {
        uimk2_arena_reset(t->a);
        t->artist = NULL;
        t->album = NULL;
        t->title = NULL;
        return UIMK2_TT_FAIL;
    }
    return UIMK2_TT_ALBUM;
}

uimk2_tt_result uimk2_track_text_set(uimk2_track_text *t, const char *artist,
                                     const char *album, const char *title) {
    uimk2_arena *a = t->a;
    bool album_same = same(t->artist, artist) && same(t->album, album);

    if (album_same && same(t->title, title)) {
        return UIMK2_TT_SAME;
    }
    if (album_same) {
        (void)uimk2_arena_rewind(a, a->song_mark);
        if (!build_title(t, title)) {
            return rebuild_after_reset(t, artist, album, title);
        }
        return UIMK2_TT_TITLE;
    }
    (void)uimk2_arena_rewind(a, a->album_mark);
    if (!build_album(t, artist, album) || !build_title(t, title)) {
        return rebuild_after_reset(t, artist, album, title);
    }
    return UIMK2_TT_ALBUM;
}
