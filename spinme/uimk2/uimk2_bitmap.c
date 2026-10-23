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
    t->row_rebuilds = 0;
    t->comb = NULL;
    t->ncomb = 0;
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

/* ---- combiner ---------------------------------------------------------- */

void uimk2_bmtab_set_combiners(uimk2_bmtab *t, const uimk2_combiner *comb,
                               uint16_t n) {
    t->comb = comb;
    t->ncomb = n;
}

void uimk2_combine(const uimk2_bmtab *t, uint8_t ci, uint8_t s[4]) {
    const uimk2_combiner *k;
    int c;
    if (ci == 0 || ci >= t->ncomb || t->comb == NULL) {
        return;
    }
    k = &t->comb[ci];
    for (c = 0; c < 4; c++) {
        if ((k->mask & (1u << c)) == 0) {
            continue;
        }
        switch ((uimk2_comb_op)k->op) {
        case UIMK2_COMB_SET:
            s[c] = k->value[c];
            break;
        case UIMK2_COMB_SCALE:
            s[c] = (uint8_t)(((uint32_t)s[c] * k->value[c] + 127u) / 255u);
            break;
        case UIMK2_COMB_CURVE: {
            /* C99 division truncates toward zero */
            int32_t v = (int32_t)s[c];
            int32_t d = (int32_t)k->value[c] - 128;
            v += d * v * (255 - v) / 32768;
            s[c] = (uint8_t)(v < 0 ? 0 : (v > 255 ? 255 : v));
            break;
        }
        default:
            break;
        }
    }
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
    const uint16_t *row; /* a root row's overlap list, or NULL */
    uint32_t rown;
} child_it;

static void it_init(child_it *it, const uimk2_bmtab *t, uint16_t parent) {
    it->t = t;
    it->p = &t->bm[parent];
    it->k = 0;
    it->run = 0;
    it->row = NULL;
    it->rown = 0;
}

/* Children of parent that may cover row y: the row's overlap list when
 * parent is a Layout whose lists are built, otherwise every child. */
static void it_init_row(child_it *it, const uimk2_bmtab *t, uint16_t parent,
                        int32_t y) {
    const uimk2_bm *p = &t->bm[parent];
    it_init(it, t, parent);
    if (p->kind == UIMK2_BM_LAYOUT && p->u.layout.rows_ok &&
        p->u.layout.row_start != NULL && y >= 0 && y < p->h) {
        const uint32_t *rs = p->u.layout.row_start;
        it->row = &p->u.layout.row_item[rs[y]];
        it->rown = rs[y + 1] - rs[y];
    }
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
        if (it->row != NULL) {
            if (it->k >= it->rown) {
                return 0;
            }
            li = &p->u.layout.items[it->row[it->k++]];
        } else {
            if (it->k >= p->u.layout.n) {
                return 0;
            }
            li = &p->u.layout.items[p->u.layout.n - 1u - it->k++];
        }
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

/* ---- scroll ------------------------------------------------------------ */

static int16_t clamp_i16(int64_t v) {
    if (v < INT16_MIN) {
        return INT16_MIN;
    }
    if (v > INT16_MAX) {
        return INT16_MAX;
    }
    return (int16_t)v;
}

void uimk2_view_scroll(uimk2_bmtab *t, uint16_t viewport, int32_t dx,
                       int32_t dy) {
    uimk2_bm *b;
    uimk2_rect box;
    if (viewport == 0 || viewport >= t->count ||
        t->bm[viewport].kind != UIMK2_BM_VIEWPORT) {
        return;
    }
    if (dx == 0 && dy == 0) {
        return;
    }
    b = &t->bm[viewport];
    b->u.viewport.ox = clamp_i16((int64_t)b->u.viewport.ox + dx);
    b->u.viewport.oy = clamp_i16((int64_t)b->u.viewport.oy + dy);
    box.x = 0;
    box.y = 0;
    box.w = b->w;
    box.h = b->h;
    uimk2_invalidate(t, viewport, box, false);
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
    it_init_row(&it, t, idx, y);
    while (acc->a < 255u && (c = it_next(&it, &dx, &dy)) != 0) {
        uint8_t s[4];
        t->samples++;
        if (sample(t, c, x - dx, y - dy, s)) {
            uimk2_combine(t, t->bm[c].combiner, s);
            covered = true;
            acc_under(acc, s);
        }
    }
    return covered;
}

/* The caller-provided pixel buffer of a node, or NULL when it has none. */
static const uint8_t *backing_px(const uimk2_bm *b) {
    switch ((uimk2_bm_kind)b->kind) {
    case UIMK2_BM_RGBA:
        return b->u.rgba.px;
    case UIMK2_BM_LAYOUT:
        return b->u.layout.px;
    default:
        return NULL;
    }
}

static bool sample(uimk2_bmtab *t, uint16_t idx, int32_t x, int32_t y,
                   uint8_t out[4]) {
    const uimk2_bm *b = &t->bm[idx];
    const uint8_t *bp;
    accum acc;
    if (x < 0 || y < 0 || x >= b->w || y >= b->h) {
        return false;
    }
    /* a clean hinted node with a buffer is its own finished picture: read
     * it and do not composite the children */
    bp = b->cache_backing && !b->dirty ? backing_px(b) : NULL;
    if (bp != NULL) {
        memcpy(out, &bp[((uint32_t)y * b->w + (uint32_t)x) * 4u], 4);
        return true;
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

/* ---- root overlap lists ------------------------------------------------ */

/* Rows [*y0, *y1) of a Layout of height h that item li overlaps. */
static void item_rows(const uimk2_bmtab *t, const uimk2_layout_item *li,
                      uint16_t h, int32_t *y0, int32_t *y1) {
    const uimk2_bm *c = &t->bm[li->idx];
    *y0 = li->y < 0 ? 0 : li->y;
    *y1 = (int32_t)li->y + c->h;
    if (*y1 > h) {
        *y1 = h;
    }
}

/* Rebuild the per-row overlap lists, front to back. rows_ok is false
 * afterwards when they do not fit in row_cap. */
static void rebuild_rows(uimk2_bmtab *t, uint16_t idx) {
    uimk2_bm *b = &t->bm[idx];
    uint32_t *rs = b->u.layout.row_start;
    uint32_t total = 0;
    int32_t y, y0, y1;
    uint16_t k;
    t->row_rebuilds++;
    b->u.layout.rows_ok = false;
    memset(rs, 0, ((size_t)b->h + 1u) * sizeof rs[0]);
    /* count into rs[y + 1], then prefix-sum into starts */
    for (k = 0; k < b->u.layout.n; k++) {
        item_rows(t, &b->u.layout.items[k], b->h, &y0, &y1);
        for (y = y0; y < y1; y++) {
            rs[y + 1]++;
        }
    }
    for (y = 0; y < b->h; y++) {
        total += rs[y + 1];
        rs[y + 1] = total;
    }
    if (total > b->u.layout.row_cap) {
        return;
    }
    /* fill front to back, using rs[y] as each row's cursor */
    for (k = b->u.layout.n; k-- > 0;) {
        item_rows(t, &b->u.layout.items[k], b->h, &y0, &y1);
        for (y = y0; y < y1; y++) {
            b->u.layout.row_item[rs[y]++] = k;
        }
    }
    /* each cursor now sits at the next row's start; shift back */
    for (y = b->h; y > 0; y--) {
        rs[y] = rs[y - 1];
    }
    rs[0] = 0;
    b->u.layout.rows_ok = true;
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
        if (b->u.layout.row_start != NULL &&
            (b->geom_dirty || !b->u.layout.rows_ok)) {
            rebuild_rows(t, idx);
        }
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

/* ---- bezel ------------------------------------------------------------- */

static int64_t diam2(uint16_t w, uint16_t h) {
    int64_t d = w < h ? w : h;
    return d * d;
}

bool uimk2_bezel_visible(uint16_t w, uint16_t h, int32_t x, int32_t y) {
    int64_t ex = 2 * (int64_t)x + 1 - w, ey = 2 * (int64_t)y + 1 - h;
    if (x < 0 || y < 0 || x >= w || y >= h) {
        return false;
    }
    return ex * ex + ey * ey <= diam2(w, h);
}

/* floor(sqrt(v)) for v >= 0 */
static int64_t isqrt64(int64_t v) {
    int64_t lo = 0, hi = 1;
    while (hi * hi <= v) {
        hi *= 2;
    }
    while (hi - lo > 1) {
        int64_t mid = lo + (hi - lo) / 2;
        if (mid * mid <= v) {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    return lo;
}

static int64_t floor_div2(int64_t v) { return v >= 0 ? v / 2 : -((1 - v) / 2); }

bool uimk2_bezel_span(uint16_t w, uint16_t h, uimk2_rect r, int32_t y,
                      int32_t *x0, int32_t *x1) {
    int64_t ey = 2 * (int64_t)y + 1 - h, rem, s, lo, hi;
    *x0 = *x1 = 0;
    if (rect_empty(r) || y < 0 || y >= h || y < r.y ||
        y >= (int32_t)r.y + r.h) {
        return false;
    }
    rem = diam2(w, h) - ey * ey;
    if (rem < 0) {
        return false;
    }
    /* |2x + 1 - w| <= s, so x in [ceil((w-1-s)/2), floor((w-1+s)/2)] */
    s = isqrt64(rem);
    lo = -floor_div2(-((int64_t)w - 1 - s));
    hi = floor_div2((int64_t)w - 1 + s) + 1;
    if (lo < 0) lo = 0;
    if (hi > w) hi = w;
    if (lo < r.x) lo = r.x;
    if (hi > (int64_t)r.x + r.w) hi = (int64_t)r.x + r.w;
    if (hi <= lo) {
        return false;
    }
    *x0 = (int32_t)lo;
    *x1 = (int32_t)hi;
    return true;
}
