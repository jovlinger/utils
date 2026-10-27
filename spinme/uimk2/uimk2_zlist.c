/* uimk2 host zlist. See uimk2_zlist.h. */
#include "uimk2_zlist.h"

#include "uimk2_blit.h"

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

/* ERROR log when a busy redraw reaches REDRAW_ATTEMPT_CAP. A board file
 * may define its own before including this translation unit. */
#ifndef UIMK2_ZLIST_LOG_ERROR
#define UIMK2_ZLIST_LOG_ERROR(cap)                                            \
    fprintf(stderr, "ERROR: redraw busy at attempt cap %u\n", (unsigned)(cap))
#endif

static void schedule_redraw_retry(uimk2_zlist *z, int attempt) {
    if (attempt < 1) {
        attempt = 1;
    }
    z->redraw_attempt = attempt;
    if (z->hold_redraw) {
        z->redraw_held = true;
        return;
    }
    if (attempt >= (int)REDRAW_ATTEMPT_CAP) {
        UIMK2_ZLIST_LOG_ERROR(REDRAW_ATTEMPT_CAP);
    }
    if (z->ring != NULL) {
        (void)uimk2_push_redraw(z->ring, attempt);
    }
}

static void swap_buffers(uimk2_zlist *z) {
    uint8_t *tmp = z->curr;
    z->curr = z->next;
    z->next = tmp;
}

/* Fill the row bitmap from the curr/next diff. Returns whether any row
 * differed. Equal rows are cleared, not left set. */
static bool fill_row_dirty(uimk2_zlist *z) {
    uint32_t y;
    uint32_t stride = PANEL_W * 4u;
    bool any = false;
    memset(z->row_dirty, 0, sizeof z->row_dirty);
    for (y = 0; y < PANEL_H; y++) {
        const uint8_t *a = z->curr + y * stride;
        const uint8_t *b = z->next + y * stride;
        if (memcmp(a, b, stride) != 0) {
            uint8_t bit = (uint8_t)(1u << (y % 8u));
            z->row_dirty[y / 8u] = (uint8_t)(z->row_dirty[y / 8u] | bit);
            any = true;
        }
    }
    return any;
}

static void compare_swap_ping(uimk2_zlist *z) {
    if (z->busy) {
        schedule_redraw_retry(z, z->redraw_attempt + 1);
        return;
    }
    if (!fill_row_dirty(z)) {
        z->redraw_attempt = 0;
        return;
    }
    swap_buffers(z);
    z->busy = true;
    z->redraw_attempt = 0;
    if (z->ping_a != NULL) {
        z->ping_a(z->ping_ctx);
    }
}

/* 24h HH:MM:SS from the global clock (CLOCK_RES millis in clock_tick). */
static void format_clock(char dst[UIMK2_ZLIST_TEXT], int32_t sec, uint32_t tick) {
    uint32_t s;
    int wrote;
    (void)sec;
    s = (tick / 1000u) % 86400u;
    memset(dst, 0, UIMK2_ZLIST_TEXT);
    wrote = snprintf(dst, UIMK2_ZLIST_TEXT, "%02u:%02u:%02u",
                     (unsigned)(s / 3600u), (unsigned)((s / 60u) % 60u),
                     (unsigned)(s % 60u));
    if (wrote < 0 || wrote >= (int)UIMK2_ZLIST_TEXT) {
        dst[0] = '\0';
    }
}

static void update_one(uimk2_zlist *z, uimk2_shape *s) {
    switch ((uimk2_update_sel)s->update_selector) {
    case UIMK2_UPD_FIXED:
        return;
    case UIMK2_UPD_SCROLL: {
        /* Endless: ox = (millis / SCROLL_MS_PER_OX) % backing_w. */
        uint16_t pw = s->pw != 0u ? s->pw : s->w;
        int16_t nx;
        int16_t ny = 0;
        if (pw == 0u) {
            return;
        }
        nx = (int16_t)((z->clock_tick / SCROLL_MS_PER_OX) % (uint32_t)pw);
        if (nx != s->ox || ny != s->oy) {
            s->ox = nx;
            s->oy = ny;
            s->dirty = true;
        }
        return;
    }
    case UIMK2_UPD_CLOCKTEXT: {
        char buf[UIMK2_ZLIST_TEXT];
        format_clock(buf, z->clock_sec, z->clock_tick);
        if (memcmp(s->text, buf, sizeof s->text) != 0) {
            memcpy(s->text, buf, sizeof s->text);
            s->dirty = true;
        }
        return;
    }
    default:
        return;
    }
}

void uimk2_zlist_update(uimk2_zlist *z) {
    uint16_t i;
    for (i = 0; i < z->n; i++) {
        update_one(z, &z->shape[i]);
    }
}

static void mark_rec(uimk2_zlist *z, uint16_t idx) {
    uimk2_shape *s = &z->shape[idx];
    uint16_t c;
    bool any = false;
    for (c = 0; c < s->nchild; c++) {
        uint16_t ci = s->child[c];
        mark_rec(z, ci);
        if (z->shape[ci].dirty) {
            any = true;
        }
    }
    if (any) {
        s->dirty = true;
    }
}

void uimk2_zlist_mark_dirty_from_children(uimk2_zlist *z, uint16_t idx) {
    if (idx >= z->n) {
        return;
    }
    mark_rec(z, idx);
}

/* Framebuffers store pack66 words (see uimk2_blit.h). Shape px sources
 * remain RGBA8888 and are packed on paint. */

static uint32_t *frame66(uint8_t *p) {
    return (uint32_t *)(void *)p;
}

static void fill_row66(uint32_t *row, uint32_t w, uint32_t word) {
    uint32_t x;
    for (x = 0; x < w; x++) {
        row[x] = word;
    }
}

static void paint_base_solid(uint8_t *dst, const uint8_t rgba[4]) {
    uint32_t word = uimk2_blit_pack66(rgba);
    uint32_t row[PANEL_W];
    uint32_t y;
    uint32_t *fb = frame66(dst);
    fill_row66(row, PANEL_W, word);
    for (y = 0; y < PANEL_H; y++) {
        memcpy(fb + y * PANEL_W, row, sizeof row);
    }
}

static void paint_base(uimk2_zlist *z, const uimk2_shape *s) {
    uint32_t y;
    uint32_t *fb;
    if (s->px == NULL) {
        paint_base_solid(z->next, s->rgba);
        return;
    }
    /* Static RGBA8888 base: pack each row (skip-RLE for A2==0). */
    fb = frame66(z->next);
    for (y = 0; y < PANEL_H; y++) {
        uimk2_blit_rgba_row_to_pack66(fb + y * PANEL_W,
                                      s->px + y * PANEL_W * 4u, PANEL_W);
    }
}

static void clip_shape(const uimk2_shape *s, int32_t *x0, int32_t *y0,
                       int32_t *x1, int32_t *y1) {
    *x0 = s->x;
    *y0 = s->y;
    *x1 = s->x + (int32_t)s->w;
    *y1 = s->y + (int32_t)s->h;
    if (*x0 < 0) {
        *x0 = 0;
    }
    if (*y0 < 0) {
        *y0 = 0;
    }
    if (*x1 > (int32_t)PANEL_W) {
        *x1 = (int32_t)PANEL_W;
    }
    if (*y1 > (int32_t)PANEL_H) {
        *y1 = (int32_t)PANEL_H;
    }
}

/* Viewport (w,h) over a full-width text map (pw,ph). Sample
 * px[(ly+oy) * pw + (lx+ox)]. Outside the map is transparent. */
static void paint_shape(uimk2_zlist *z, const uimk2_shape *s) {
    int32_t x0;
    int32_t y0;
    int32_t x1;
    int32_t y1;
    int32_t y;
    int32_t x;
    uint32_t *fb = frame66(z->next);
    uint32_t tmp[PANEL_W];
    uint32_t bw;
    uint16_t pw;
    uint16_t ph;
    uint8_t miss[4];
    clip_shape(s, &x0, &y0, &x1, &y1);
    if (x0 >= x1 || y0 >= y1) {
        return;
    }
    bw = (uint32_t)(x1 - x0);
    if (s->px != NULL) {
        pw = s->pw != 0u ? s->pw : s->w;
        ph = s->ph != 0u ? s->ph : s->h;
        miss[0] = 0;
        miss[1] = 0;
        miss[2] = 0;
        miss[3] = 0;
        for (y = y0; y < y1; y++) {
            int32_t ly = y - (int32_t)s->y;
            int32_t sy = ly + (int32_t)s->oy;
            for (x = x0; x < x1; x++) {
                int32_t lx = x - (int32_t)s->x;
                int32_t sx = lx + (int32_t)s->ox;
                uint32_t ti = (uint32_t)(x - x0);
                if (s->update_selector == (uint8_t)UIMK2_UPD_SCROLL &&
                    pw > 0u) {
                    /* Endless wrap over the backing map. */
                    sx %= (int32_t)pw;
                    if (sx < 0) {
                        sx += (int32_t)pw;
                    }
                    if (ph > 0u) {
                        sy %= (int32_t)ph;
                        if (sy < 0) {
                            sy += (int32_t)ph;
                        }
                    }
                }
                if (sx < 0 || sy < 0 || sx >= (int32_t)pw ||
                    sy >= (int32_t)ph) {
                    tmp[ti] = uimk2_blit_pack66(miss);
                } else {
                    const uint8_t *src =
                        s->px + ((uint32_t)sy * (uint32_t)pw + (uint32_t)sx) *
                                    4u;
                    tmp[ti] = uimk2_blit_pack66(src);
                }
            }
            uimk2_blit_encode_row_skips(tmp, bw);
            uimk2_blit_src_over66(fb + (uint32_t)y * PANEL_W + (uint32_t)x0, bw,
                                  tmp, bw, bw, 1u, bw, 1u);
        }
        return;
    }
    {
        uint32_t word = uimk2_blit_pack66(s->rgba);
        fill_row66(tmp, bw, word);
        for (y = y0; y < y1; y++) {
            memcpy(fb + (uint32_t)y * PANEL_W + (uint32_t)x0, tmp,
                   bw * sizeof(uint32_t));
        }
    }
}

void uimk2_zlist_render(uimk2_zlist *z) {
    uint16_t k;
    /* No clear of next. High index (far) down to 0 (near). */
    for (k = z->n; k > 0; k--) {
        uimk2_shape *s = &z->shape[k - 1u];
        if (s->is_base) {
            paint_base(z, s);
        } else {
            paint_shape(z, s);
        }
        s->dirty = false;
    }
}

void uimk2_zlist_update_render_draw(uimk2_zlist *z) {
    uint16_t i;
    uimk2_zlist_update(z);
    for (i = 0; i < z->nroot; i++) {
        uimk2_zlist_mark_dirty_from_children(z, z->root[i]);
    }
    uimk2_zlist_render(z);
    compare_swap_ping(z);
}

void uimk2_zlist_redraw(uimk2_zlist *z, int attempt) {
    if (attempt < 0) {
        attempt = 0;
    }
    z->redraw_attempt = attempt;
    compare_swap_ping(z);
}

void uimk2_zlist_set_clock(uimk2_zlist *z, int32_t sec, uint32_t tick) {
    z->clock_sec = sec;
    z->clock_tick = tick;
}

static bool exterior_has(const uimk2_shape *s, int x, int y) {
    int32_t x0 = s->x;
    int32_t y0 = s->y;
    int32_t x1 = x0 + (int32_t)s->w;
    int32_t y1 = y0 + (int32_t)s->h;
    int32_t px = x;
    int32_t py = y;
    return px >= x0 && py >= y0 && px < x1 && py < y1;
}

/* Opacity percent: alpha/255 >= pct/100, i.e. alpha * 100 >= pct * 255.
 * pct 0 is off and accepts every sample. */
static bool alpha_ok(uint8_t alpha, unsigned pct) {
    if (pct == 0u) {
        return true;
    }
    return (unsigned)alpha * 100u >= pct * 255u;
}

static uint8_t shape_alpha(const uimk2_shape *s, int x, int y) {
    uint32_t off;
    int32_t lx;
    int32_t ly;
    if (s->px == NULL) {
        return s->rgba[3];
    }
    if (s->is_base) {
        if (x < 0 || y < 0 || x >= (int)PANEL_W || y >= (int)PANEL_H) {
            return 0;
        }
        off = ((uint32_t)y * PANEL_W + (uint32_t)x) * 4u + 3u;
        return s->px[off];
    }
    lx = (int32_t)x - (int32_t)s->x;
    ly = (int32_t)y - (int32_t)s->y;
    if (lx < 0 || ly < 0 || lx >= (int32_t)s->w || ly >= (int32_t)s->h) {
        return 0;
    }
    {
        uint16_t pw = s->pw != 0u ? s->pw : s->w;
        uint16_t ph = s->ph != 0u ? s->ph : s->h;
        int32_t sx = lx + (int32_t)s->ox;
        int32_t sy = ly + (int32_t)s->oy;
        if (s->update_selector == (uint8_t)UIMK2_UPD_SCROLL && pw > 0u) {
            sx %= (int32_t)pw;
            if (sx < 0) {
                sx += (int32_t)pw;
            }
            if (ph > 0u) {
                sy %= (int32_t)ph;
                if (sy < 0) {
                    sy += (int32_t)ph;
                }
            }
        }
        if (sx < 0 || sy < 0 || sx >= (int32_t)pw || sy >= (int32_t)ph) {
            return 0;
        }
        off = ((uint32_t)sy * (uint32_t)pw + (uint32_t)sx) * 4u + 3u;
        return s->px[off];
    }
}

int uimk2_zlist_hit_test_pct(const uimk2_zlist *z, int x, int y, unsigned pct) {
    uint16_t i;
    if (z == NULL) {
        return -1;
    }
    for (i = 0; i < z->n; i++) {
        const uimk2_shape *s = &z->shape[i];
        if (!s->accept_hit) {
            continue;
        }
        if (!exterior_has(s, x, y)) {
            continue;
        }
        if (pct != 0u && !alpha_ok(shape_alpha(s, x, y), pct)) {
            continue;
        }
        return (int)i;
    }
    return -1;
}

int uimk2_zlist_hit_test(const uimk2_zlist *z, int x, int y) {
    return uimk2_zlist_hit_test_pct(z, x, y, HIT_OPAQUE_PCT);
}

bool uimk2_zlist_row_dirty(const uimk2_zlist *z, uint16_t y) {
    uint8_t bit;
    if (y >= (uint16_t)PANEL_H) {
        return false;
    }
    bit = (uint8_t)(1u << (y % 8u));
    return (z->row_dirty[y / 8u] & bit) != 0;
}

static bool copy_shape(uimk2_shape *s, const uimk2_shape_desc *d, uint16_t n) {
    uint16_t c;
    if (d->nchildren > (uint16_t)UIMK2_SHAPE_MAX_CHILDREN) {
        return false;
    }
    if (d->nchildren > 0 && d->children == NULL) {
        return false;
    }
    s->update_selector = d->update_selector;
    s->is_base = d->is_base;
    s->accept_hit = d->accept_hit;
    s->is_transport = d->is_transport;
    s->x = d->x;
    s->y = d->y;
    s->w = d->w;
    s->h = d->h;
    s->pw = d->pw;
    s->ph = d->ph;
    s->step_x = d->step_x;
    s->step_y = d->step_y;
    s->px = d->px;
    s->rgba[0] = d->rgba[0];
    s->rgba[1] = d->rgba[1];
    s->rgba[2] = d->rgba[2];
    s->rgba[3] = d->rgba[3];
    s->nchild = d->nchildren;
    for (c = 0; c < d->nchildren; c++) {
        if (d->children[c] >= n) {
            return false;
        }
        s->child[c] = d->children[c];
    }
    return true;
}

/* False when a child edge closes a cycle. */
static bool walk_ok(const uimk2_shape *sh, uint16_t n, uint16_t idx,
                    uint8_t *on_path) {
    uint16_t c;
    if (idx >= n || on_path[idx]) {
        return false;
    }
    on_path[idx] = 1u;
    for (c = 0; c < sh[idx].nchild; c++) {
        if (!walk_ok(sh, n, sh[idx].child[c], on_path)) {
            return false;
        }
    }
    on_path[idx] = 0u;
    return true;
}

static bool forest_ok(const uimk2_shape *sh, uint16_t n) {
    uint16_t i;
    uint8_t on_path[UIMK2_ZLIST_MAX];
    for (i = 0; i < n; i++) {
        memset(on_path, 0, sizeof on_path);
        if (!walk_ok(sh, n, i, on_path)) {
            return false;
        }
    }
    return true;
}

static void collect_roots(uimk2_zlist *z) {
    uint8_t is_child[UIMK2_ZLIST_MAX];
    uint16_t i, c;
    memset(is_child, 0, sizeof is_child);
    for (i = 0; i < z->n; i++) {
        for (c = 0; c < z->shape[i].nchild; c++) {
            is_child[z->shape[i].child[c]] = 1u;
        }
    }
    z->nroot = 0;
    for (i = 0; i < z->n; i++) {
        if (!is_child[i]) {
            z->root[z->nroot++] = i;
        }
    }
}

static bool fail_build(uimk2_zlist *z) {
    memset(z, 0, sizeof *z);
    return false;
}

bool uimk2_zlist_build(uimk2_zlist *z, const uimk2_shape_desc *desc, uint16_t n,
                       uint8_t *curr, uint8_t *next, uimk2_ring *ring,
                       uimk2_zlist_ping_fn ping_a, void *ping_ctx) {
    uint16_t i;
    if (z == NULL || curr == NULL || next == NULL) {
        return false;
    }
    if (n > (uint16_t)UIMK2_ZLIST_MAX || (n > 0 && desc == NULL)) {
        return fail_build(z);
    }
    memset(z, 0, sizeof *z);
    for (i = 0; i < n; i++) {
        if (!copy_shape(&z->shape[i], &desc[i], n)) {
            return fail_build(z);
        }
    }
    if (!forest_ok(z->shape, n)) {
        return fail_build(z);
    }
    z->n = n;
    collect_roots(z);
    z->curr = curr;
    z->next = next;
    z->ring = ring;
    z->ping_a = ping_a;
    z->ping_ctx = ping_ctx;
    return true;
}
