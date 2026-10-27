/* uimk2 host zlist. See uimk2_zlist.h. */
#include "uimk2_zlist.h"

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

static int16_t clamp_add(int16_t cur, int16_t step) {
    int32_t sum = (int32_t)cur + (int32_t)step;
    if (sum > 32767) {
        sum = 32767;
    }
    if (sum < -32768) {
        sum = -32768;
    }
    return (int16_t)sum;
}

static void format_clock(char dst[UIMK2_ZLIST_TEXT], int32_t sec, uint32_t tick) {
    int wrote;
    memset(dst, 0, UIMK2_ZLIST_TEXT);
    wrote = snprintf(dst, UIMK2_ZLIST_TEXT, "%" PRId32 ":%" PRIu32, sec, tick);
    if (wrote < 0 || wrote >= (int)UIMK2_ZLIST_TEXT) {
        dst[0] = '\0';
    }
}

static void update_one(uimk2_zlist *z, uimk2_shape *s) {
    switch ((uimk2_update_sel)s->update_selector) {
    case UIMK2_UPD_FIXED:
        return;
    case UIMK2_UPD_SCROLL: {
        int16_t nx = clamp_add(s->ox, s->step_x);
        int16_t ny = clamp_add(s->oy, s->step_y);
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

static void paint_base_solid(uint8_t *dst, const uint8_t rgba[4]) {
    uint32_t stride = PANEL_W * 4u;
    uint32_t x, y;
    uint8_t row[PANEL_W * 4u];
    for (x = 0; x < PANEL_W; x++) {
        row[x * 4u + 0u] = rgba[0];
        row[x * 4u + 1u] = rgba[1];
        row[x * 4u + 2u] = rgba[2];
        row[x * 4u + 3u] = rgba[3];
    }
    for (y = 0; y < PANEL_H; y++) {
        memcpy(dst + y * stride, row, stride);
    }
}

static void paint_base(uimk2_zlist *z, const uimk2_shape *s) {
    uint32_t nbytes = (uint32_t)UIMK2_FRAME_BYTES;
    if (s->px != NULL) {
        memcpy(z->next, s->px, nbytes);
        return;
    }
    paint_base_solid(z->next, s->rgba);
}

static void paint_shape(uimk2_zlist *z, const uimk2_shape *s) {
    int32_t x0 = s->x;
    int32_t y0 = s->y;
    int32_t x1 = x0 + (int32_t)s->w;
    int32_t y1 = y0 + (int32_t)s->h;
    int32_t x, y;
    if (x0 < 0) {
        x0 = 0;
    }
    if (y0 < 0) {
        y0 = 0;
    }
    if (x1 > (int32_t)PANEL_W) {
        x1 = (int32_t)PANEL_W;
    }
    if (y1 > (int32_t)PANEL_H) {
        y1 = (int32_t)PANEL_H;
    }
    for (y = y0; y < y1; y++) {
        for (x = x0; x < x1; x++) {
            uint32_t off = ((uint32_t)y * PANEL_W + (uint32_t)x) * 4u;
            uint8_t *dst = z->next + off;
            if (s->px != NULL) {
                int32_t lx = x - s->x;
                int32_t ly = y - s->y;
                uint32_t so = ((uint32_t)ly * (uint32_t)s->w + (uint32_t)lx) * 4u;
                const uint8_t *src = s->px + so;
                dst[0] = src[0];
                dst[1] = src[1];
                dst[2] = src[2];
                dst[3] = src[3];
            } else {
                dst[0] = s->rgba[0];
                dst[1] = s->rgba[1];
                dst[2] = s->rgba[2];
                dst[3] = s->rgba[3];
            }
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
    s->x = d->x;
    s->y = d->y;
    s->w = d->w;
    s->h = d->h;
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
