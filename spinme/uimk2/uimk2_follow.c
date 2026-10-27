#include "uimk2_follow.h"

#include <string.h>

#include "uimk2_glyphs.h"

enum {
    COMB_ZONE = 1,
    COMB_INK = 2,
    COMB_DESIRED = 3,
    COMB_FADE = 4,
    COMB_BLACK = 5
};

static const uint8_t BLACK[4] = {0, 0, 0, 255};
static const uint8_t CLEAR[4] = {0, 0, 0, 0};
static const uint8_t WHITE[4] = {255, 255, 255, 255};

static const uimk2_combiner COMBS[6] = {
    {0, 0, {0, 0, 0, 0}},
    {UIMK2_COMB_RGB, UIMK2_COMB_SET, {255, 220, 0, 0}},
    {UIMK2_COMB_RGB, UIMK2_COMB_SET, {255, 255, 255, 0}},
    {UIMK2_COMB_RGB, UIMK2_COMB_SET, {0, 255, 255, 0}},
    {UIMK2_COMB_A, UIMK2_COMB_SCALE, {0, 0, 0, 128}},
    {UIMK2_COMB_RGB, UIMK2_COMB_SET, {0, 0, 0, 0}},
};

static const int PAD_X = 12;
static const int PAD_Y = 6;
static const int LEFT = 24;

static int clamp_vol(int v) {
    if (v < 0) {
        return 0;
    }
    if (v > 100) {
        return 100;
    }
    return v;
}

static void copy_cap(char *dst, const char *src) {
    uint32_t i;
    if (src == NULL) {
        src = "";
    }
    for (i = 0; i + 1u < UIMK2_FOLLOW_TEXT && src[i] != 0; i++) {
        dst[i] = src[i];
    }
    dst[i] = 0;
}

static char widest_digit(void) {
    char best = '0';
    uint16_t bw = 0;
    int d;
    for (d = 0; d < 10; d++) {
        const uimk2_glyph_entry *e = uimk2_glyph_find((uint32_t)('0' + d));
        if (e != NULL && e->width >= bw) {
            bw = e->width;
            best = (char)('0' + d);
        }
    }
    return best;
}

static void drop_headers(uimk2_bmtab *t, uint16_t first) {
    uint16_t i;
    for (i = first; i < t->count; i++) {
        memset(&t->bm[i], 0, sizeof t->bm[i]);
    }
    t->count = first;
}

static void retarget_digits(uimk2_follow *f, uimk2_line *line, int value) {
    char digits[3];
    int i;
    digits[0] = (char)('0' + value / 100);
    digits[1] = (char)('0' + (value / 10) % 10);
    digits[2] = (char)('0' + value % 10);
    for (i = 0; i < 3; i++) {
        const uimk2_glyph_entry *e = uimk2_glyph_find((uint32_t)digits[i]);
        uimk2_bm *g = &f->bm.bm[line->idx[i]];
        g->w = e->width;
        g->h = uimk2_glyph_h;
        g->u.glyph.alpha = &uimk2_glyph_alpha[e->offset];
    }
    uimk2_bm_measure(&f->bm, line->pack);
    uimk2_cache_dirty(&f->bm, line->cache);
}

static void add_item(uimk2_follow *f, uint16_t idx, int x, int y) {
    uimk2_layout_item *it = &f->items[f->nitems++];
    it->x = (int16_t)x;
    it->y = (int16_t)y;
    it->idx = idx;
    f->bm.bm[idx].parent = f->root;
}

static void place(uimk2_follow *f) {
    uimk2_rect all;
    int y;
    uint16_t label;
    int lw;
    f->nitems = 0;
    add_item(f, f->button, f->button_x, f->button_y);
    label = f->showing_stop ? f->stop.cache : f->play.cache;
    lw = f->bm.bm[label].w;
    add_item(f, label, f->button_x + (f->button_w - lw) / 2,
             f->button_y + (f->button_h - (int)f->bm.bm[label].h) / 2);
    y = f->button_y + f->button_h + 8;
    add_item(f, f->zone.cache, LEFT, y);
    y += (int)f->bm.bm[f->zone.cache].h + 12;
    add_item(f, f->artist.cache, LEFT, y);
    y += (int)f->bm.bm[f->artist.cache].h + 4;
    add_item(f, f->album.cache, LEFT, y);
    y += (int)f->bm.bm[f->album.cache].h + 12;
    add_item(f, f->title.cache, LEFT, y);
    y += (int)f->bm.bm[f->title.cache].h + 4;
    f->volume_x = LEFT;
    f->volume_y = y;
    add_item(f, f->volume.cache, f->volume_x, f->volume_y);
    if (f->overlay) {
        add_item(f, f->desired.cache, f->volume_x, f->volume_y);
    }
    f->bm.bm[f->root].u.layout.items = f->items;
    f->bm.bm[f->root].u.layout.n = f->nitems;
    all.x = 0;
    all.y = 0;
    all.w = f->sw;
    all.h = f->sh;
    uimk2_invalidate(&f->bm, f->root, all, true);
}

static bool build_dynamic(uimk2_follow *f, const char *artist, const char *album,
                          const char *title, bool album_change) {
    if (f->artist.cache != 0) {
        uint32_t mark = album_change ? f->arena.album_mark : f->arena.song_mark;
        uint16_t hdr = album_change ? f->artist.first_hdr : f->title.first_hdr;
        if (!uimk2_arena_rewind(&f->arena, mark)) {
            return false;
        }
        drop_headers(&f->bm, hdr);
        if (album_change) {
            f->artist.cache = 0;
            f->album.cache = 0;
        }
        f->title.cache = 0;
    }
    if (f->artist.cache == 0) {
        if (!uimk2_line_build(&f->bm, &f->arena, &f->artist, artist, 1, COMB_INK,
                              BLACK)) {
            return false;
        }
        if (!uimk2_line_build(&f->bm, &f->arena, &f->album, album, 1, COMB_INK,
                              BLACK)) {
            return false;
        }
        uimk2_arena_mark_song(&f->arena);
    }
    if (!uimk2_line_build(&f->bm, &f->arena, &f->title, title, 1, COMB_INK,
                          BLACK)) {
        return false;
    }
    return true;
}

bool uimk2_follow_init(uimk2_follow *f, uimk2_bm *storage, uint16_t cap,
                       void *arena_buf, uint32_t arena_cap, uint8_t *screen,
                       uint16_t sw, uint16_t sh) {
    char wide[4];
    char digit;
    int play_w, stop_w;
    uint32_t i, npx;
    memset(f, 0, sizeof *f);
    uimk2_bmtab_init(&f->bm, storage, cap);
    uimk2_bmtab_set_combiners(&f->bm, COMBS, 6);
    uimk2_arena_init(&f->arena, arena_buf, arena_cap);
    f->screen = screen;
    f->sw = sw;
    f->sh = sh;
    f->root = uimk2_bm_new(&f->bm, UIMK2_BM_LAYOUT);
    f->bm.root = f->root;
    f->bm.bm[f->root].w = sw;
    f->bm.bm[f->root].h = sh;
    f->bm.bm[f->root].u.layout.px = screen;
    memcpy(f->bm.bm[f->root].u.layout.paper, BLACK, 4);

    if (!uimk2_line_build(&f->bm, &f->arena, &f->zone, "spinme", 1, COMB_ZONE,
                          BLACK)) {
        return false;
    }
    if (!uimk2_line_build(&f->bm, &f->arena, &f->play, "play", 1, COMB_BLACK,
                          WHITE)) {
        return false;
    }
    if (!uimk2_line_build(&f->bm, &f->arena, &f->stop, "stop", 1, COMB_BLACK,
                          WHITE)) {
        return false;
    }
    play_w = f->bm.bm[f->play.cache].w;
    stop_w = f->bm.bm[f->stop.cache].w;
    f->button_w = (play_w > stop_w ? play_w : stop_w) + PAD_X * 2;
    f->button_h = (int)uimk2_glyph_h + PAD_Y * 2;
    f->button_x = ((int)sw - f->button_w) / 2;
    f->button_y = 8;
    npx = (uint32_t)f->button_w * (uint32_t)f->button_h;
    f->button = uimk2_bm_new(&f->bm, UIMK2_BM_RGBA);
    f->bm.bm[f->button].w = (uint16_t)f->button_w;
    f->bm.bm[f->button].h = (uint16_t)f->button_h;
    f->bm.bm[f->button].u.rgba.px = (uint8_t *)uimk2_arena_alloc(&f->arena, npx * 4u);
    if (f->bm.bm[f->button].u.rgba.px == NULL) {
        return false;
    }
    for (i = 0; i < npx; i++) {
        memcpy(f->bm.bm[f->button].u.rgba.px + i * 4u, WHITE, 4);
    }

    digit = widest_digit();
    wide[0] = wide[1] = wide[2] = digit;
    wide[3] = 0;
    if (!uimk2_line_build(&f->bm, &f->arena, &f->volume, wide, 1, COMB_INK,
                          BLACK)) {
        return false;
    }
    if (!uimk2_line_build(&f->bm, &f->arena, &f->desired, wide, 1, COMB_DESIRED,
                          CLEAR)) {
        return false;
    }
    f->bm.bm[f->desired.cache].combiner = COMB_FADE;
    uimk2_arena_seal(&f->arena);
    if (!build_dynamic(f, "", "", "", true)) {
        return false;
    }
    f->showing_stop = false;
    f->vol = 0;
    f->desired_vol = 0;
    f->overlay = false;
    place(f);
    retarget_digits(f, &f->volume, 0);
    retarget_digits(f, &f->desired, 0);
    return true;
}

void uimk2_follow_set_sched(uimk2_follow *f, uimk2_sched *sched) {
    f->sched = sched;
}

bool uimk2_follow_set_text(uimk2_follow *f, const char *artist, const char *album,
                           const char *title) {
    char a[UIMK2_FOLLOW_TEXT], b[UIMK2_FOLLOW_TEXT], c[UIMK2_FOLLOW_TEXT];
    bool album_change;
    copy_cap(a, artist);
    copy_cap(b, album);
    copy_cap(c, title);
    if (strcmp(a, f->artist_s) == 0 && strcmp(b, f->album_s) == 0 &&
        strcmp(c, f->title_s) == 0) {
        return true;
    }
    album_change = strcmp(a, f->artist_s) != 0 || strcmp(b, f->album_s) != 0;
    if (!build_dynamic(f, a, b, c, album_change)) {
        return false;
    }
    memcpy(f->artist_s, a, UIMK2_FOLLOW_TEXT);
    memcpy(f->album_s, b, UIMK2_FOLLOW_TEXT);
    memcpy(f->title_s, c, UIMK2_FOLLOW_TEXT);
    place(f);
    return true;
}

void uimk2_follow_set_status(uimk2_follow *f, const char *status) {
    bool stop = status != NULL && strcmp(status, "play") == 0;
    if (stop == f->showing_stop) {
        return;
    }
    f->showing_stop = stop;
    place(f);
}

void uimk2_follow_set_volume(uimk2_follow *f, int volume) {
    bool was = f->overlay;
    f->vol = clamp_vol(volume);
    f->overlay = f->desired_vol != f->vol;
    retarget_digits(f, &f->volume, f->vol);
    if (was != f->overlay) {
        place(f);
    }
}

bool uimk2_follow_knob(uimk2_follow *f, int delta, uint32_t now_ms) {
    bool was = f->overlay;
    bool posted = true;
    f->desired_vol = clamp_vol(f->desired_vol + delta);
    f->overlay = f->desired_vol != f->vol;
    retarget_digits(f, &f->desired, f->desired_vol);
    if (was != f->overlay) {
        place(f);
    }
    if (f->sched != NULL) {
        posted = uimk2_sched_detent(f->sched, now_ms, 0, 0, f->desired_vol, 0);
    }
    return posted;
}

bool uimk2_follow_touch(uimk2_follow *f, int x, int y, uint32_t now_ms) {
    bool hit = x >= f->button_x && y >= f->button_y &&
               x < f->button_x + f->button_w && y < f->button_y + f->button_h;
    if (!hit || f->sched == NULL) {
        return hit;
    }
    uimk2_sched_touch(f->sched, now_ms, x, y);
    uimk2_sched_post_toggle(f->sched);
    return true;
}

bool uimk2_follow_snapshot(uimk2_follow *f, const char *artist, const char *album,
                           const char *title, int volume) {
    if (!uimk2_follow_set_text(f, artist, album, title)) {
        return false;
    }
    uimk2_follow_set_volume(f, volume);
    if (f->sched != NULL) {
        uimk2_sched_snapshot(f->sched);
    }
    return true;
}

uimk2_rect uimk2_follow_repaint(uimk2_follow *f) {
    return uimk2_repaint(&f->bm);
}
