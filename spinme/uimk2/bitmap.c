#include "bitmap.h"

#include <stddef.h>

int rect_empty(Rect r) { return r.w <= 0 || r.h <= 0; }

Rect rect_union(Rect a, Rect b) {
  if (rect_empty(a)) return b;
  if (rect_empty(b)) return a;
  int32_t x0 = a.x < b.x ? a.x : b.x;
  int32_t y0 = a.y < b.y ? a.y : b.y;
  int32_t x1 = a.x + a.w > b.x + b.w ? a.x + a.w : b.x + b.w;
  int32_t y1 = a.y + a.h > b.y + b.h ? a.y + a.h : b.y + b.h;
  Rect r = {x0, y0, x1 - x0, y1 - y0};
  return r;
}

static int owns_pixels(const Bitmap *b) { return b->pix != NULL; }

void bm_measure(BitmapTable *t, uint16_t idx) {
  Bitmap *b = &t->b[idx];
  int32_t sum = 0, mx = 0, n = 0;
  if (b->kind != BM_L2R && b->kind != BM_T2B) return;
  for (const uint16_t *p = b->list; *p; p++) {
    const Bitmap *c = &t->b[*p];
    int32_t along = b->kind == BM_L2R ? c->w : c->h;
    int32_t cross = b->kind == BM_L2R ? c->h : c->w;
    sum += along;
    if (cross > mx) mx = cross;
    n++;
  }
  if (n > 1) sum += (n - 1) * b->sep;
  if (b->kind == BM_L2R) {
    b->w = sum;
    b->h = mx;
  } else {
    b->w = mx;
    b->h = sum;
  }
}

/* L2R: bottom aligned on the cross axis. T2B: centered on the cross axis. */
int bm_child_offset(const BitmapTable *t, uint16_t parent, uint16_t child,
                    int32_t *ox, int32_t *oy) {
  const Bitmap *p = &t->b[parent];
  switch (p->kind) {
    case BM_LAYOUT:
      for (uint16_t i = 0; i < p->nitems; i++) {
        if (p->items[i].idx == child) {
          *ox = p->items[i].x;
          *oy = p->items[i].y;
          return 0;
        }
      }
      return -1;
    case BM_L2R: {
      int32_t x = 0;
      for (const uint16_t *q = p->list; *q; q++) {
        const Bitmap *c = &t->b[*q];
        if (*q == child) {
          *ox = x;
          *oy = p->h - c->h;
          return 0;
        }
        x += c->w + p->sep;
      }
      return -1;
    }
    case BM_T2B: {
      int32_t y = 0;
      for (const uint16_t *q = p->list; *q; q++) {
        const Bitmap *c = &t->b[*q];
        if (*q == child) {
          *ox = (p->w - c->w) / 2;
          *oy = y;
          return 0;
        }
        y += c->h + p->sep;
      }
      return -1;
    }
    case BM_VIEWPORT:
      if (p->child != child) return -1;
      *ox = -p->ox;
      *oy = -p->oy;
      return 0;
    case BM_RGBA:
      if (p->child != child) return -1;
      *ox = 0;
      *oy = 0;
      return 0;
    default:
      return -1;
  }
}

int bm_build_rows(BitmapTable *t, uint16_t idx) {
  Bitmap *b = &t->b[idx];
  if (b->kind != BM_LAYOUT || !b->rowlist || b->rowcap == 0) return -1;
  for (int32_t y = 0; y < b->h; y++) {
    uint16_t *row = b->rowlist + (size_t)y * b->rowcap;
    uint16_t n = 0;
    for (uint16_t i = 0; i < b->nitems; i++) {
      const LayoutItem *it = &b->items[i];
      const Bitmap *c = &t->b[it->idx];
      if (y < it->y || y >= it->y + c->h) continue;
      if (n + 1 >= b->rowcap) {
        row[n] = 0;
        return -1;
      }
      row[n++] = it->idx;
    }
    row[n] = 0;
  }
  b->rows_valid = 1;
  t->row_rebuilds++;
  return 0;
}

void bm_invalidate(BitmapTable *t, uint16_t idx, Rect r, int geometry) {
  while (idx) {
    Bitmap *b = &t->b[idx];
    b->damage = rect_union(b->damage, r);
    b->dirty = 1;
    if (geometry) b->geom_dirty = 1;
    uint16_t par = b->parent;
    if (par) {
      int32_t ox = 0, oy = 0;
      if (bm_child_offset(t, par, idx, &ox, &oy) == 0) {
        r.x += ox;
        r.y += oy;
      }
    }
    idx = par;
  }
}

/* ---- sampling ---------------------------------------------------------- */

static uint32_t mul255(uint32_t a, uint32_t b) { return (a * b + 127) / 255; }

typedef struct {
  uint32_t pr, pg, pb, a; /* premultiplied accumulator */
} Acc;

/* Add a straight-alpha sample behind what is already accumulated. */
static void acc_add(Acc *acc, const uint8_t s[4]) {
  uint32_t room = 255 - acc->a;
  acc->pr += mul255(mul255(s[0], s[3]), room);
  acc->pg += mul255(mul255(s[1], s[3]), room);
  acc->pb += mul255(mul255(s[2], s[3]), room);
  acc->a += mul255(s[3], room);
}

static void acc_straight(const Acc *acc, uint8_t out[4]) {
  if (acc->a == 0) {
    out[0] = out[1] = out[2] = out[3] = 0;
    return;
  }
  uint32_t r = (acc->pr * 255 + acc->a / 2) / acc->a;
  uint32_t g = (acc->pg * 255 + acc->a / 2) / acc->a;
  uint32_t b = (acc->pb * 255 + acc->a / 2) / acc->a;
  out[0] = (uint8_t)(r > 255 ? 255 : r);
  out[1] = (uint8_t)(g > 255 ? 255 : g);
  out[2] = (uint8_t)(b > 255 ? 255 : b);
  out[3] = (uint8_t)(acc->a > 255 ? 255 : acc->a);
}

static int sample(BitmapTable *t, uint16_t idx, int32_t x, int32_t y,
                  uint8_t out[4]);

/* Apply the node's combiner to one sample; channels outside the mask pass
 * through. */
static void apply_combiner(const BitmapTable *t, uint16_t cidx, uint8_t s[4]) {
  if (cidx == 0 || cidx >= t->ncombiners) return;
  const Combiner *c = &t->combiners[cidx];
  for (int ch = 0; ch < 4; ch++) {
    if (!(c->mask & (1u << ch))) continue;
    if (c->op == COMB_SET) s[ch] = c->value[ch];
  }
}

/* Sample one child of a composite at (x, y) in the composite's coordinates,
 * adding it to acc. Returns 1 when the child covers the point. */
static int add_child(BitmapTable *t, uint16_t parent, uint16_t child,
                     int32_t x, int32_t y, Acc *acc) {
  int32_t ox = 0, oy = 0;
  uint8_t s[4];
  if (bm_child_offset(t, parent, child, &ox, &oy) != 0) return 0;
  if (!sample(t, child, x - ox, y - oy, s)) return 0;
  acc_add(acc, s);
  return 1;
}

static int sample_raw(BitmapTable *t, uint16_t idx, int32_t x, int32_t y,
                      uint8_t out[4]) {
  const Bitmap *b = &t->b[idx];
  Acc acc = {0, 0, 0, 0};
  int hit = 0;
  if (idx == 0 || x < 0 || y < 0 || x >= b->w || y >= b->h) return 0;
  switch (b->kind) {
    case BM_RGBA:
    case BM_LAYOUT:
      if (owns_pixels(b)) {
        const uint8_t *p = b->pix + ((size_t)y * (size_t)b->w + (size_t)x) * 4;
        out[0] = p[0];
        out[1] = p[1];
        out[2] = p[2];
        out[3] = p[3];
        t->samples++;
        return 1;
      }
      if (b->kind == BM_RGBA) return 0;
      for (int i = (int)b->nitems - 1; i >= 0 && acc.a < 255; i--)
        hit |= add_child(t, idx, b->items[i].idx, x, y, &acc);
      break;
    case BM_L2R:
    case BM_T2B:
      for (const uint16_t *q = b->list; *q && acc.a < 255; q++)
        hit |= add_child(t, idx, *q, x, y, &acc);
      break;
    case BM_VIEWPORT:
      hit = add_child(t, idx, b->child, x, y, &acc);
      break;
    case BM_GLYPH:
      out[0] = out[1] = out[2] = 255;
      out[3] = b->alpha[(size_t)y * (size_t)b->w + (size_t)x];
      t->samples++;
      return 1;
    default:
      return 0;
  }
  acc_straight(&acc, out);
  return hit;
}

static int sample(BitmapTable *t, uint16_t idx, int32_t x, int32_t y,
                  uint8_t out[4]) {
  int hit = sample_raw(t, idx, x, y, out);
  if (hit) apply_combiner(t, t->b[idx].combiner, out);
  return hit;
}

/* ---- repaint ----------------------------------------------------------- */

/* Children of a node for the dirty-first pass. Returns the count. */
static int children(const BitmapTable *t, uint16_t idx, uint16_t *out,
                    int max) {
  const Bitmap *b = &t->b[idx];
  int n = 0;
  if (b->kind == BM_LAYOUT) {
    for (uint16_t i = 0; i < b->nitems && n < max; i++)
      out[n++] = b->items[i].idx;
  } else if (b->kind == BM_L2R || b->kind == BM_T2B) {
    for (const uint16_t *q = b->list; *q && n < max; q++) out[n++] = *q;
  } else if ((b->kind == BM_VIEWPORT || b->kind == BM_RGBA) && b->child &&
             n < max) {
    out[n++] = b->child;
  }
  return n;
}

#define BM_MAX_CHILDREN 64

static void write_paper(const Bitmap *b, uint8_t *p) {
  p[0] = b->paper[0];
  p[1] = b->paper[1];
  p[2] = b->paper[2];
  p[3] = b->paper[3];
}

static void paint_owner(BitmapTable *t, uint16_t idx) {
  Bitmap *b = &t->b[idx];
  Rect d = b->damage;
  int32_t x0 = d.x < 0 ? 0 : d.x, y0 = d.y < 0 ? 0 : d.y;
  int32_t x1 = d.x + d.w > b->w ? b->w : d.x + d.w;
  int32_t y1 = d.y + d.h > b->h ? b->h : d.y + d.h;
  uint16_t kids[BM_MAX_CHILDREN];
  int nk = children(t, idx, kids, BM_MAX_CHILDREN);
  for (int32_t y = y0; y < y1; y++) {
    for (int32_t x = x0; x < x1; x++) {
      uint8_t *p = b->pix + ((size_t)y * (size_t)b->w + (size_t)x) * 4;
      Acc acc = {0, 0, 0, 0};
      int hit = 0;
      /* front to back: a later Layout item is in front */
      if (b->kind == BM_LAYOUT && b->rows_valid) {
        const uint16_t *row = b->rowlist + (size_t)y * b->rowcap;
        int cnt = 0;
        while (row[cnt]) cnt++;
        for (int i = cnt - 1; i >= 0 && acc.a < 255; i--)
          hit |= add_child(t, idx, row[i], x, y, &acc);
      } else if (b->kind == BM_LAYOUT) {
        for (int i = nk - 1; i >= 0 && acc.a < 255; i--)
          hit |= add_child(t, idx, kids[i], x, y, &acc);
      } else {
        for (int i = 0; i < nk && acc.a < 255; i++)
          hit |= add_child(t, idx, kids[i], x, y, &acc);
      }
      if (!hit || acc.a == 0) {
        write_paper(b, p);
        continue;
      }
      if (acc.a < 255) {
        uint8_t paper[4];
        paper[0] = b->paper[0];
        paper[1] = b->paper[1];
        paper[2] = b->paper[2];
        paper[3] = b->paper[3];
        acc_add(&acc, paper);
      }
      acc_straight(&acc, p);
    }
  }
}

void bm_repaint(BitmapTable *t, uint16_t idx) {
  Bitmap *b = &t->b[idx];
  uint16_t kids[BM_MAX_CHILDREN];
  if (idx == 0 || !b->dirty) return;
  int nk = children(t, idx, kids, BM_MAX_CHILDREN);
  for (int i = 0; i < nk; i++) bm_repaint(t, kids[i]);
  if (b->kind == BM_LAYOUT && b->rowlist && (b->geom_dirty || !b->rows_valid))
    (void)bm_build_rows(t, idx);
  /* pixel data with no children (a plain bitmap) has nothing to repaint */
  if (owns_pixels(b) && nk > 0) paint_owner(t, idx);
  b->dirty = 0;
  b->geom_dirty = 0;
  b->damage.x = b->damage.y = b->damage.w = b->damage.h = 0;
}

/* ---- round bezel clip -------------------------------------------------- */

static int32_t isqrt32(int64_t v) {
  int64_t r = 0;
  while ((r + 1) * (r + 1) <= v) r++;
  return (int32_t)r;
}

void bm_bezel_span(int32_t w, int32_t h, int32_t y, int32_t *x0, int32_t *x1) {
  int32_t d = w < h ? w : h;
  int64_t dy = 2 * (int64_t)y + 1 - h;
  int64_t rem = (int64_t)d * d - dy * dy;
  *x0 = *x1 = 0;
  if (y < 0 || y >= h || rem < 0) return;
  /* pixel x is inside when |2x + 1 - w| <= s */
  int32_t s = isqrt32(rem);
  int32_t lo = w - 1 - s; /* 2x >= lo */
  int32_t hi = w - 1 + s; /* 2x <= hi */
  int32_t a = lo <= 0 ? 0 : (lo + 1) / 2;
  int32_t z = hi < 0 ? -1 : hi / 2;
  if (a < 0) a = 0;
  if (z > w - 1) z = w - 1;
  if (z < a) return;
  *x0 = a;
  *x1 = z + 1;
}

void bm_blit_bezel(const BitmapTable *t, uint16_t idx, Rect r, BlitFn fn,
                   void *ctx) {
  const Bitmap *b = &t->b[idx];
  int32_t xa = r.x < 0 ? 0 : r.x, ya = r.y < 0 ? 0 : r.y;
  int32_t xb = r.x + r.w > b->w ? b->w : r.x + r.w;
  int32_t yb = r.y + r.h > b->h ? b->h : r.y + r.h;
  if (!b->pix) return;
  for (int32_t y = ya; y < yb; y++) {
    int32_t s0, s1;
    bm_bezel_span(b->w, b->h, y, &s0, &s1);
    if (s0 < xa) s0 = xa;
    if (s1 > xb) s1 = xb;
    if (s1 <= s0) continue;
    fn(ctx, s0, y, s1 - s0, b->pix + ((size_t)y * (size_t)b->w + (size_t)s0) * 4);
  }
}
