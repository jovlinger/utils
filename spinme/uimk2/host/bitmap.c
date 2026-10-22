#include <string.h>

#include "bitmap.h"

/* Front-to-back accumulator. num[k] holds sum(c_k * w) over the layers taken
 * so far, and a holds sum(w), so a straight color is num / a. */
typedef struct {
    uint32_t num[3];
    uint32_t a;
} Acc;

static void acc_add(Acc *acc, const uint8_t c[4])
{
    uint32_t t = 255u - acc->a;
    uint32_t w = ((uint32_t)c[3] * t + 127u) / 255u;
    int k;

    if (w == 0) {
        return;
    }
    for (k = 0; k < 3; k++) {
        acc->num[k] += (uint32_t)c[k] * w;
    }
    acc->a += w;
}

static void acc_color(const Acc *acc, uint8_t out[4])
{
    int k;

    out[3] = (uint8_t)acc->a;
    for (k = 0; k < 3; k++) {
        out[k] = acc->a ? (uint8_t)((acc->num[k] + acc->a / 2u) / acc->a) : 0;
    }
}

static int rect_empty(BmRect r)
{
    return r.w <= 0 || r.h <= 0;
}

static BmRect rect_union(BmRect a, BmRect b)
{
    BmRect r;
    int x0, y0, x1, y1;

    if (rect_empty(a)) {
        return b;
    }
    if (rect_empty(b)) {
        return a;
    }
    x0 = a.x < b.x ? a.x : b.x;
    y0 = a.y < b.y ? a.y : b.y;
    x1 = (a.x + a.w) > (b.x + b.w) ? (a.x + a.w) : (b.x + b.w);
    y1 = (a.y + a.h) > (b.y + b.h) ? (a.y + a.h) : (b.y + b.h);
    r.x = (int16_t)x0;
    r.y = (int16_t)y0;
    r.w = (int16_t)(x1 - x0);
    r.h = (int16_t)(y1 - y0);
    return r;
}

/* Maps a rect in child coordinates into parent coordinates. */
static BmRect to_parent(const BitmapTable *t, uint16_t p, uint16_t child,
                        BmRect r)
{
    const Bitmap *pn = &t->nodes[p];
    uint16_t i;

    for (i = 0; i < pn->n_items; i++) {
        const LayoutItem *it = &t->items[pn->first_item + i];
        if (it->idx == child) {
            r.x = (int16_t)(r.x + it->x);
            r.y = (int16_t)(r.y + it->y);
            break;
        }
    }
    if (pn->kind == BM_KIND_VIEWPORT) {
        r.x = (int16_t)(r.x - pn->ox);
        r.y = (int16_t)(r.y - pn->oy);
    }
    return r;
}

static void sample(BitmapTable *t, uint16_t idx, int x, int y, uint8_t out[4]);

/* Composites the children of idx that cover (x, y), in node coordinates,
 * front to back. Stops as soon as the accumulator is opaque. */
static void composite_children(BitmapTable *t, uint16_t idx, int x, int y,
                               Acc *acc)
{
    const Bitmap *n = &t->nodes[idx];
    int px = x, py = y;
    uint16_t i;

    if (n->kind == BM_KIND_VIEWPORT) {
        if (x < 0 || y < 0 || x >= n->w || y >= n->h) {
            return;
        }
        px += n->ox;
        py += n->oy;
    }
    for (i = 0; i < n->n_items && acc->a < 255u; i++) {
        LayoutItem it = t->items[n->first_item + i];
        const Bitmap *c = &t->nodes[it.idx];
        int cx = px - it.x;
        int cy = py - it.y;
        uint8_t s[4];

        if (cx < 0 || cy < 0 || cx >= c->w || cy >= c->h) {
            continue;
        }
        t->child_samples++;
        sample(t, it.idx, cx, cy, s);
        acc_add(acc, s);
    }
}

/* Straight RGBA of node idx at (x, y), in its own coordinates. */
static void sample(BitmapTable *t, uint16_t idx, int x, int y, uint8_t out[4])
{
    Bitmap *n = &t->nodes[idx];
    Acc acc;

    if (n->pixels) {
        memcpy(out, n->pixels + ((size_t)y * n->w + (size_t)x) * 4u, 4);
        return;
    }
    if (n->kind == BM_KIND_GLYPH) {
        memset(out, 0, 4);
        return;
    }
    memset(&acc, 0, sizeof acc);
    composite_children(t, idx, x, y, &acc);
    acc_color(&acc, out);
}

static void composite_owner(BitmapTable *t, uint16_t idx)
{
    Bitmap *n = &t->nodes[idx];
    int x0 = n->damage.x < 0 ? 0 : n->damage.x;
    int y0 = n->damage.y < 0 ? 0 : n->damage.y;
    int x1 = n->damage.x + n->damage.w;
    int y1 = n->damage.y + n->damage.h;
    int x, y;

    if (x1 > n->w) {
        x1 = n->w;
    }
    if (y1 > n->h) {
        y1 = n->h;
    }
    for (y = y0; y < y1; y++) {
        for (x = x0; x < x1; x++) {
            Acc acc;
            uint8_t paper[4];
            uint8_t *dst = n->pixels + ((size_t)y * n->w + (size_t)x) * 4u;

            memset(&acc, 0, sizeof acc);
            composite_children(t, idx, x, y, &acc);
            if (acc.a < 255u) {
                paper[0] = n->paper[0];
                paper[1] = n->paper[1];
                paper[2] = n->paper[2];
                paper[3] = 255;
                acc_add(&acc, paper);
            }
            acc_color(&acc, dst);
        }
    }
}

void bm_init(BitmapTable *t)
{
    memset(t, 0, sizeof *t);
    t->n_nodes = 1; /* index 0 is null */
}

uint16_t bm_new(BitmapTable *t, uint8_t kind, uint16_t w, uint16_t h)
{
    uint16_t idx;
    Bitmap *n;

    if (t->n_nodes >= BM_MAX_NODES) {
        return BM_NULL;
    }
    idx = t->n_nodes++;
    n = &t->nodes[idx];
    memset(n, 0, sizeof *n);
    n->kind = kind;
    n->w = w;
    n->h = h;
    return idx;
}

void bm_set_owner(BitmapTable *t, uint16_t idx, uint8_t *px,
                  const uint8_t paper[3])
{
    Bitmap *n = &t->nodes[idx];

    n->pixels = px;
    memcpy(n->paper, paper, 3);
}

int bm_set_children(BitmapTable *t, uint16_t parent,
                    const LayoutItem *items, uint16_t n)
{
    Bitmap *p = &t->nodes[parent];
    uint16_t i;

    if ((unsigned)t->n_items + n > BM_MAX_ITEMS) {
        return 0;
    }
    for (i = 0; i < n; i++) {
        if (items[i].idx == BM_NULL || items[i].idx >= t->n_nodes) {
            return 0;
        }
    }
    p->first_item = t->n_items;
    p->n_items = n;
    for (i = 0; i < n; i++) {
        t->items[t->n_items + i] = items[i];
        t->nodes[items[i].idx].parent = parent;
    }
    t->n_items = (uint16_t)(t->n_items + n);
    return 1;
}

void bm_set_viewport_origin(BitmapTable *t, uint16_t idx, int16_t ox,
                            int16_t oy)
{
    t->nodes[idx].ox = ox;
    t->nodes[idx].oy = oy;
}

void bm_invalidate(BitmapTable *t, uint16_t idx, BmRect r, int geometry)
{
    uint16_t cur = idx;

    while (cur != BM_NULL) {
        Bitmap *n = &t->nodes[cur];
        uint16_t up = n->parent;

        n->damage = n->dirty ? rect_union(n->damage, r) : r;
        n->dirty = 1;
        if (geometry) {
            n->geom_dirty = 1;
        }
        if (up == BM_NULL) {
            break;
        }
        r = to_parent(t, up, cur, r);
        cur = up;
    }
}

void bm_repaint(BitmapTable *t, uint16_t idx)
{
    Bitmap *n = &t->nodes[idx];
    BmRect zero = {0, 0, 0, 0};
    uint16_t i;

    if (!n->dirty) {
        return;
    }
    for (i = 0; i < n->n_items; i++) {
        uint16_t child = t->items[n->first_item + i].idx;
        if (t->nodes[child].dirty) {
            bm_repaint(t, child);
        }
    }
    if (n->pixels) {
        composite_owner(t, idx);
    }
    n->dirty = 0;
    n->geom_dirty = 0;
    n->damage = zero;
}
