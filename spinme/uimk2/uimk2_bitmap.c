#include "uimk2_bitmap.h"

#include <stddef.h>
#include <string.h>

/* ---- rects ------------------------------------------------------------- */

static bool rect_empty(uimk2_rect r) { return r.w == 0 || r.h == 0; }

static uimk2_rect rect_make(int32_t x0, int32_t y0, int32_t x1, int32_t y1) {
    uimk2_rect r = {0, 0, 0, 0};
    if (x1 > x0 && y1 > y0) {
        r.x = (int16_t)x0;
        r.y = (int16_t)y0;
        r.w = (uint16_t)(x1 - x0);
        r.h = (uint16_t)(y1 - y0);
    }
    return r;
}

uimk2_rect uimk2_rect_union(uimk2_rect a, uimk2_rect b) {
    int32_t x0, y0, x1, y1;
    if (rect_empty(a)) {
        return b;
    }
    if (rect_empty(b)) {
        return a;
    }
    x0 = a.x < b.x ? a.x : b.x;
    y0 = a.y < b.y ? a.y : b.y;
    x1 = (int32_t)a.x + a.w > (int32_t)b.x + b.w ? (int32_t)a.x + a.w
                                                  : (int32_t)b.x + b.w;
    y1 = (int32_t)a.y + a.h > (int32_t)b.y + b.h ? (int32_t)a.y + a.h
                                                  : (int32_t)b.y + b.h;
    return rect_make(x0, y0, x1, y1);
}

/* r clipped to (0, 0, w, h). */
static uimk2_rect rect_clip_box(uimk2_rect r, uint16_t w, uint16_t h) {
    int32_t x0 = r.x, y0 = r.y;
    int32_t x1 = (int32_t)r.x + r.w, y1 = (int32_t)r.y + r.h;
    if (rect_empty(r)) {
        return r;
    }
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > w) x1 = w;
    if (y1 > h) y1 = h;
    return rect_make(x0, y0, x1, y1);
}

/* ---- table ------------------------------------------------------------- */

void uimk2_bmtab_init(uimk2_bmtab *t, uimk2_bm *storage, uint16_t cap) {
    t->bm = storage;
    t->cap = cap;
    t->count = 1;
    t->root = 0;
    t->samples = 0;
    if (cap > 0) {
        memset(&storage[0], 0, sizeof storage[0]);
    }
}

uint16_t uimk2_bm_new(uimk2_bmtab *t, uimk2_bm_kind kind) {
    uint16_t i;
    if (t->count >= t->cap) {
        return 0;
    }
    i = t->count++;
    memset(&t->bm[i], 0, sizeof t->bm[i]);
    t->bm[i].kind = (uint8_t)kind;
    return i;
}

/* ---- children ---------------------------------------------------------- */

/* Children front to back with their offsets in the parent. A Layout stores
 * its items back to front, so it is walked in reverse. L2R and T2B children
 * do not overlap. */
typedef struct {
    const uimk2_bmtab *t;
    const uimk2_bm *p;
    uint16_t k;
    int32_t run;
} child_it;

static void it_init(child_it *it, const uimk2_bmtab *t, uint16_t parent) {
    it->t = t;
    it->p = &t->bm[parent];
    it->k = 0;
    it->run = 0;
}

static uint16_t it_next(child_it *it, int32_t *dx, int32_t *dy) {
    const uimk2_bm *p = it->p;
    const uimk2_bm *c;
    uint16_t idx;
    switch ((uimk2_bm_kind)p->kind) {
    case UIMK2_BM_RGBA:
        if (it->k++ > 0 || p->u.rgba.child == 0) {
            return 0;
        }
        *dx = 0;
        *dy = 0;
        return p->u.rgba.child;
    case UIMK2_BM_LAYOUT: {
        const uimk2_layout_item *li;
        if (it->k >= p->u.layout.n) {
            return 0;
        }
        li = &p->u.layout.items[p->u.layout.n - 1u - it->k++];
        *dx = li->x;
        *dy = li->y;
        return li->idx;
    }
    case UIMK2_BM_L2R:
    case UIMK2_BM_T2B:
        if (p->u.pack.items == NULL) {
            return 0;
        }
        idx = p->u.pack.items[it->k];
        if (idx == 0) {
            return 0;
        }
        it->k++;
        c = &it->t->bm[idx];
        if (p->kind == UIMK2_BM_L2R) {
            *dx = it->run;
            *dy = (int32_t)p->h - c->h;
            it->run += (int32_t)c->w + p->u.pack.sep;
        } else {
            *dx = ((int32_t)p->w - c->w) / 2;
            *dy = it->run;
            it->run += (int32_t)c->h + p->u.pack.sep;
        }
        return idx;
    case UIMK2_BM_VIEWPORT:
        if (it->k++ > 0 || p->u.viewport.child == 0) {
            return 0;
        }
        *dx = -(int32_t)p->u.viewport.ox;
        *dy = -(int32_t)p->u.viewport.oy;
        return p->u.viewport.child;
    case UIMK2_BM_NULL:
    case UIMK2_BM_GLYPH:
    default:
        return 0;
    }
}

bool uimk2_bm_child_offset(const uimk2_bmtab *t, uint16_t parent,
                           uint16_t child, int32_t *dx, int32_t *dy) {
    child_it it;
    uint16_t c;
    it_init(&it, t, parent);
    while ((c = it_next(&it, dx, dy)) != 0) {
        if (c == child) {
            return true;
        }
    }
    return false;
}

void uimk2_bm_measure(uimk2_bmtab *t, uint16_t idx) {
    uimk2_bm *p = &t->bm[idx];
    uint32_t along = 0, cross = 0;
    uint16_t k, n = 0;
    if (p->kind != UIMK2_BM_L2R && p->kind != UIMK2_BM_T2B) {
        return;
    }
    for (k = 0; p->u.pack.items != NULL && p->u.pack.items[k] != 0; k++) {
        const uimk2_bm *c = &t->bm[p->u.pack.items[k]];
        uint16_t a = p->kind == UIMK2_BM_L2R ? c->w : c->h;
        uint16_t x = p->kind == UIMK2_BM_L2R ? c->h : c->w;
        along += a;
        if (x > cross) {
            cross = x;
        }
        n++;
    }
    if (n > 1) {
        along += (uint32_t)(n - 1u) * p->u.pack.sep;
    }
    if (p->kind == UIMK2_BM_L2R) {
        p->w = (uint16_t)along;
        p->h = (uint16_t)cross;
    } else {
        p->w = (uint16_t)cross;
        p->h = (uint16_t)along;
    }
}

/* ---- invalidate -------------------------------------------------------- */

void uimk2_invalidate(uimk2_bmtab *t, uint16_t node, uimk2_rect r,
                      bool geometry) {
    while (node != 0) {
        uimk2_bm *b = &t->bm[node];
        uint16_t parent = b->parent;
        int32_t dx, dy;
        r = rect_clip_box(r, b->w, b->h);
        b->damage = uimk2_rect_union(b->damage, r);
        b->dirty = true;
        b->geom_dirty = b->geom_dirty || geometry;
        if (parent == 0 || !uimk2_bm_child_offset(t, parent, node, &dx, &dy)) {
            return;
        }
        if (!rect_empty(r)) {
            r = rect_make(r.x + dx, r.y + dy, (int32_t)r.x + r.w + dx,
                          (int32_t)r.y + r.h + dy);
        }
        node = parent;
    }
}

/* ---- sampling and blend ------------------------------------------------ */

/* Front-to-back straight-alpha src-over. cp holds premultiplied color in
 * units of 1/255; a is the accumulated alpha. */
typedef struct {
    uint32_t cp[3];
    uint32_t a;
} accum;

static void acc_under(accum *acc, const uint8_t s[4]) {
    uint32_t contrib = ((255u - acc->a) * s[3] + 127u) / 255u;
    acc->cp[0] += contrib * s[0];
    acc->cp[1] += contrib * s[1];
    acc->cp[2] += contrib * s[2];
    acc->a += contrib;
}

static void acc_out(const accum *acc, uint8_t out[4]) {
    int c;
    if (acc->a == 0) {
        memset(out, 0, 4);
        return;
    }
    for (c = 0; c < 3; c++) {
        uint32_t v = (acc->cp[c] + acc->a / 2u) / acc->a;
        out[c] = (uint8_t)(v > 255u ? 255u : v);
    }
    out[3] = (uint8_t)acc->a;
}

static bool sample(uimk2_bmtab *t, uint16_t idx, int32_t x, int32_t y,
                   uint8_t out[4]);

/* Composite the children of idx covering (x, y), front to back, stopping
 * when the accumulator is opaque. Returns whether any child covered. */
static bool composite(uimk2_bmtab *t, uint16_t idx, int32_t x, int32_t y,
                      accum *acc) {
    child_it it;
    uint16_t c;
    int32_t dx, dy;
    bool covered = false;
    it_init(&it, t, idx);
    while (acc->a < 255u && (c = it_next(&it, &dx, &dy)) != 0) {
        uint8_t s[4];
        t->samples++;
        if (sample(t, c, x - dx, y - dy, s)) {
            covered = true;
            acc_under(acc, s);
        }
    }
    return covered;
}

static bool sample(uimk2_bmtab *t, uint16_t idx, int32_t x, int32_t y,
                   uint8_t out[4]) {
    const uimk2_bm *b = &t->bm[idx];
    accum acc;
    if (x < 0 || y < 0 || x >= b->w || y >= b->h) {
        return false;
    }
    switch ((uimk2_bm_kind)b->kind) {
    case UIMK2_BM_RGBA:
        memcpy(out, &b->u.rgba.px[((uint32_t)y * b->w + (uint32_t)x) * 4u], 4);
        return true;
    case UIMK2_BM_GLYPH:
        out[0] = out[1] = out[2] = 255;
        out[3] = b->u.glyph.alpha[(uint32_t)y * b->w + (uint32_t)x];
        return true;
    case UIMK2_BM_LAYOUT:
        if (b->u.layout.px != NULL) {
            memcpy(out,
                   &b->u.layout.px[((uint32_t)y * b->w + (uint32_t)x) * 4u], 4);
            return true;
        }
        /* a Layout without a buffer is sampled through its children */
        memset(&acc, 0, sizeof acc);
        if (!composite(t, idx, x, y, &acc)) {
            return false;
        }
        acc_out(&acc, out);
        return true;
    case UIMK2_BM_L2R:
    case UIMK2_BM_T2B:
    case UIMK2_BM_VIEWPORT:
        memset(&acc, 0, sizeof acc);
        if (!composite(t, idx, x, y, &acc)) {
            return false;
        }
        acc_out(&acc, out);
        return true;
    case UIMK2_BM_NULL:
    default:
        return false;
    }
}

/* ---- repaint ----------------------------------------------------------- */

/* Recompose the owner's damage rect into px; uncovered pixels take paper,
 * and paper is the backmost layer under a covered pixel that is not
 * opaque. */
static void recompose(uimk2_bmtab *t, uint16_t idx, uint8_t *px,
                      const uint8_t paper[4]) {
    const uimk2_bm *b = &t->bm[idx];
    uimk2_rect r = rect_clip_box(b->damage, b->w, b->h);
    int32_t x, y;
    for (y = r.y; y < (int32_t)r.y + r.h; y++) {
        for (x = r.x; x < (int32_t)r.x + r.w; x++) {
            uint8_t *dst = &px[((uint32_t)y * b->w + (uint32_t)x) * 4u];
            accum acc;
            memset(&acc, 0, sizeof acc);
            if (!composite(t, idx, x, y, &acc)) {
                memcpy(dst, paper, 4);
                continue;
            }
            if (acc.a < 255u) {
                acc_under(&acc, paper);
            }
            acc_out(&acc, dst);
        }
    }
}

static void repaint_node(uimk2_bmtab *t, uint16_t idx) {
    uimk2_bm *b = &t->bm[idx];
    child_it it;
    uint16_t c;
    int32_t dx, dy;
    if (!b->dirty) {
        return;
    }
    it_init(&it, t, idx);
    while ((c = it_next(&it, &dx, &dy)) != 0) {
        repaint_node(t, c);
    }
    if (b->kind == UIMK2_BM_RGBA && b->u.rgba.child != 0) {
        recompose(t, idx, b->u.rgba.px, b->u.rgba.paper);
    } else if (b->kind == UIMK2_BM_LAYOUT && b->u.layout.px != NULL) {
        recompose(t, idx, b->u.layout.px, b->u.layout.paper);
    }
    b->dirty = false;
    b->geom_dirty = false;
    memset(&b->damage, 0, sizeof b->damage);
}

uimk2_rect uimk2_repaint(uimk2_bmtab *t) {
    uimk2_rect blit = {0, 0, 0, 0};
    uimk2_bm *root;
    if (t->root == 0) {
        return blit;
    }
    root = &t->bm[t->root];
    if (root->dirty) {
        blit = rect_clip_box(root->damage, root->w, root->h);
    }
    repaint_node(t, t->root);
    return blit;
}
